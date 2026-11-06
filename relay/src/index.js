const HEX_TOKEN = /^[0-9a-f]{64,200}$/i;
const COLLAPSE = /^[A-Za-z0-9-]{1,64}$/;
const MAX_BODY = 1024;
const JWT_LIFETIME = 40 * 60;
const RECORD_TTL = 180 * 86400;
const HOSTS = { production: "https://api.push.apple.com", development: "https://api.sandbox.push.apple.com" };

const PAYLOADS = {
  alert: {
    type: "alert",
    priority: "10",
    body: { aps: { alert: { title: "Waypoint", body: "Open Waypoint to see an update." }, "mutable-content": 1, sound: "default" } },
  },
  background: { type: "background", priority: "5", body: { aps: { "content-available": 1 } } },
};

const enc = new TextEncoder();

const b64u = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function sha256(text) {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(text)));
}

function random(bytes) {
  return b64u(crypto.getRandomValues(new Uint8Array(bytes)));
}

function same(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function reply(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

async function readCapped(request) {
  const declared = Number(request.headers.get("Content-Length"));
  if (Number.isFinite(declared) && declared > MAX_BODY) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > MAX_BODY) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) {
    all.set(c, at);
    at += c.length;
  }
  return new TextDecoder().decode(all);
}

async function readJson(request) {
  const text = await readCapped(request);
  if (text === null) return { tooBig: true };
  if (!text.trim()) return { value: {} };
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value) ? { value } : { bad: true };
  } catch {
    return { bad: true };
  }
}

let cachedJwt = null;

export async function apnsJwt(env, now = Date.now()) {
  const seconds = Math.floor(now / 1000);
  if (cachedJwt && cachedJwt.keyId === env.APNS_KEY_ID && cachedJwt.expires > seconds + 60) return cachedJwt.token;
  const pem = env.APNS_KEY.replace(/-----(BEGIN|END) PRIVATE KEY-----|\s/g, "");
  const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const head = b64u(enc.encode(JSON.stringify({ alg: "ES256", kid: env.APNS_KEY_ID })));
  const claims = b64u(enc.encode(JSON.stringify({ iss: env.APNS_TEAM_ID, iat: seconds })));
  const signature = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(`${head}.${claims}`));
  const token = `${head}.${claims}.${b64u(signature)}`;
  cachedJwt = { keyId: env.APNS_KEY_ID, token, expires: seconds + JWT_LIFETIME };
  return token;
}

export function forgetJwt() {
  cachedJwt = null;
}

async function limited(binding, key) {
  if (!binding) return false;
  const { success } = await binding.limit({ key });
  return !success;
}

async function register(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (await limited(env.REGISTER_LIMIT, ip) || await limited(env.REGISTER_ALL_LIMIT, "all")) {
    return reply(429, { error: "Too many registrations. Try again in a minute." });
  }
  const { value, tooBig, bad } = await readJson(request);
  if (tooBig) return reply(413, { error: "Request too large." });
  if (bad) return reply(400, { error: "Send a JSON object." });
  const token = typeof value.apns_token === "string" ? value.apns_token.toLowerCase() : "";
  const environment = value.environment ?? "production";
  if (!HEX_TOKEN.test(token)) return reply(400, { error: "apns_token must be the device token as hex." });
  if (!Object.hasOwn(HOSTS, environment)) return reply(400, { error: "environment must be production or development." });
  const byToken = `t:${await sha256(`${environment}:${token}`)}`;
  const id = (await env.DEVICES.get(byToken)) || random(12);
  const secret = random(32);
  const record = { token, environment, secret: await sha256(secret), created: Date.now() };
  await env.DEVICES.put(`d:${id}`, JSON.stringify(record), { expirationTtl: RECORD_TTL });
  await env.DEVICES.put(byToken, id, { expirationTtl: RECORD_TTL });
  return reply(201, { device_id: id, secret });
}

async function authenticate(request, env, id) {
  const m = /^Bearer\s+(\S+)$/.exec(request.headers.get("Authorization") || "");
  const raw = await env.DEVICES.get(`d:${id}`);
  const record = raw ? JSON.parse(raw) : null;
  const presented = m ? await sha256(m[1]) : "";
  const ok = record !== null && same(record.secret, presented);
  return ok ? record : null;
}

async function wake(request, env, deps, id) {
  const record = await authenticate(request, env, id);
  if (!record) return reply(401, { error: "Unknown device or wrong secret." });
  if (await limited(env.WAKE_LIMIT, id)) return reply(429, { error: "Too many wake-ups for this device." });
  const { value, tooBig, bad } = await readJson(request);
  if (tooBig) return reply(413, { error: "Request too large." });
  if (bad) return reply(400, { error: "Send a JSON object." });
  const kind = value.kind ?? "alert";
  const shape = Object.hasOwn(PAYLOADS, kind) ? PAYLOADS[kind] : undefined;
  if (!shape) return reply(400, { error: "kind must be alert or background." });
  const collapse = value.collapse_id;
  if (collapse !== undefined && !(typeof collapse === "string" && COLLAPSE.test(collapse))) {
    return reply(400, { error: "collapse_id must be 1 to 64 letters, digits or dashes." });
  }
  const headers = {
    authorization: `bearer ${await apnsJwt(env, deps.now?.())}`,
    "apns-topic": env.APNS_TOPIC,
    "apns-push-type": shape.type,
    "apns-priority": shape.priority,
    "content-type": "application/json",
  };
  if (collapse) headers["apns-collapse-id"] = collapse;
  let sent;
  try {
    sent = await deps.fetch(`${HOSTS[record.environment]}/3/device/${record.token}`, {
      method: "POST",
      headers,
      body: JSON.stringify(shape.body),
    });
  } catch {
    return reply(502, { error: "Couldn't reach Apple's push service." });
  }
  if (sent.status === 200) return reply(200, { ok: true });
  if (sent.status === 410 || sent.status === 400) {
    const why = await sent.json().catch(() => ({}));
    if (sent.status === 410 || why.reason === "BadDeviceToken" || why.reason === "Unregistered") {
      if (typeof why.timestamp === "number" && why.timestamp < record.created) {
        return reply(409, { error: "Apple's answer is older than this registration. Try again." });
      }
      await forget(env, id, record);
      return reply(410, { error: "That device is no longer registered with Apple. Register it again." });
    }
  }
  return reply(502, { error: `Apple's push service said ${sent.status}.` });
}

async function forget(env, id, record) {
  await env.DEVICES.delete(`d:${id}`);
  await env.DEVICES.delete(`t:${await sha256(`${record.environment}:${record.token}`)}`);
}

async function remove(request, env, id) {
  const record = await authenticate(request, env, id);
  if (!record) return reply(401, { error: "Unknown device or wrong secret." });
  await forget(env, id, record);
  return reply(200, { ok: true });
}

export async function handle(request, env, deps = { fetch: (...a) => fetch(...a) }) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === "/healthz") return reply(200, { ok: true });
  if (path === "/v1/devices") {
    return request.method === "POST" ? register(request, env) : reply(405, { error: "POST only." });
  }
  const m = /^\/v1\/devices\/([A-Za-z0-9_-]{8,64})(\/wake)?$/.exec(path);
  if (m) {
    if (m[2]) return request.method === "POST" ? wake(request, env, deps, m[1]) : reply(405, { error: "POST only." });
    return request.method === "DELETE" ? remove(request, env, m[1]) : reply(405, { error: "DELETE only." });
  }
  return reply(404, { error: "Not found." });
}

export default {
  fetch: (request, env) => handle(request, env),
};
