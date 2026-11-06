import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";
import { webcrypto } from "node:crypto";
import { apnsJwt, forgetJwt, handle } from "../src/index.js";

const TOKEN = "ab".repeat(32);
const ISSUER = { id: "KEYID12345", team: "TEAMID1234" };

class FakeKV {
  constructor() { this.map = new Map(); }
  async get(k) { return this.map.get(k) ?? null; }
  async put(k, v) { this.map.set(k, v); }
  async delete(k) { this.map.delete(k); }
}

function limiter(allowed) {
  const calls = [];
  return { calls, limit: async ({ key }) => { calls.push(key); return { success: allowed() }; } };
}

async function environment() {
  const pair = await webcrypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const der = Buffer.from(await webcrypto.subtle.exportKey("pkcs8", pair.privateKey)).toString("base64");
  const pem = `-----BEGIN PRIVATE KEY-----\n${der.match(/.{1,64}/g).join("\n")}\n-----END PRIVATE KEY-----\n`;
  return {
    publicKey: pair.publicKey,
    env: { DEVICES: new FakeKV(), APNS_KEY: pem, APNS_KEY_ID: ISSUER.id, APNS_TEAM_ID: ISSUER.team, APNS_TOPIC: "com.example.waypoint" },
  };
}

const post = (path, body, headers = {}) => new Request(`https://relay.test${path}`, {
  method: "POST", body: body === undefined ? undefined : JSON.stringify(body), headers,
});

let ctx, sent, appleStatus, appleBody;
const deps = () => ({
  fetch: async (url, init) => { sent.push({ url, ...init }); return new Response(JSON.stringify(appleBody), { status: appleStatus }); },
});

beforeEach(async () => {
  ctx = await environment();
  sent = [];
  appleStatus = 200;
  appleBody = {};
  forgetJwt();
});

async function register(over = {}) {
  const r = await handle(post("/v1/devices", { apns_token: TOKEN, ...over }), ctx.env, deps());
  return { status: r.status, body: await r.json() };
}

describe("registering", () => {
  test("gives back an id and a secret and stores only a hash of the secret", async () => {
    const { status, body } = await register();
    assert.equal(status, 201);
    assert.match(body.device_id, /^[A-Za-z0-9_-]{8,}$/);
    assert.ok(body.secret.length >= 40);
    const stored = JSON.parse(await ctx.env.DEVICES.get(`d:${body.device_id}`));
    assert.notEqual(stored.secret, body.secret);
    assert.equal(stored.token, TOKEN);
  });

  test("registering the same device again keeps its id and replaces its secret", async () => {
    const first = (await register()).body;
    const second = (await register({ apns_token: TOKEN.toUpperCase() })).body;
    assert.equal(second.device_id, first.device_id);
    assert.notEqual(second.secret, first.secret);
    const wake = await handle(post(`/v1/devices/${first.device_id}/wake`, {}, { Authorization: `Bearer ${first.secret}` }), ctx.env, deps());
    assert.equal(wake.status, 401);
  });

  test("refuses a token that is not hex, an unknown environment, a list and an oversized body", async () => {
    assert.equal((await register({ apns_token: "not hex" })).status, 400);
    assert.equal((await register({ environment: "staging" })).status, 400);
    const list = await handle(new Request("https://relay.test/v1/devices", { method: "POST", body: "[]" }), ctx.env, deps());
    assert.equal(list.status, 400);
    const big = await handle(new Request("https://relay.test/v1/devices", { method: "POST", body: "x".repeat(2000) }), ctx.env, deps());
    assert.equal(big.status, 413);
  });

  test("is limited per address", async () => {
    ctx.env.REGISTER_LIMIT = limiter(() => false);
    const r = await handle(post("/v1/devices", { apns_token: TOKEN }, { "CF-Connecting-IP": "203.0.113.9" }), ctx.env, deps());
    assert.equal(r.status, 429);
    assert.deepEqual(ctx.env.REGISTER_LIMIT.calls, ["203.0.113.9"]);
  });
});

describe("waking a device", () => {
  async function registered() {
    const { body } = await register();
    return { id: body.device_id, auth: { Authorization: `Bearer ${body.secret}` } };
  }

  test("sends Apple a fixed alert with nothing from the caller in it", async () => {
    const { id, auth } = await registered();
    const r = await handle(post(`/v1/devices/${id}/wake`, { kind: "alert", collapse_id: "trip-1", title: "Secret", body: "Flight AA1" }, auth), ctx.env, deps());
    assert.equal(r.status, 200);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].url, `https://api.push.apple.com/3/device/${TOKEN}`);
    assert.equal(sent[0].headers["apns-topic"], "com.example.waypoint");
    assert.equal(sent[0].headers["apns-push-type"], "alert");
    assert.equal(sent[0].headers["apns-collapse-id"], "trip-1");
    const payload = JSON.parse(sent[0].body);
    assert.equal(payload.aps.alert.title, "Waypoint");
    assert.equal(payload.aps["mutable-content"], 1);
    assert.equal(sent[0].body.includes("Secret"), false);
    assert.equal(sent[0].body.includes("AA1"), false);
  });

  test("sends a silent background push when asked", async () => {
    const { id, auth } = await registered();
    await handle(post(`/v1/devices/${id}/wake`, { kind: "background" }, auth), ctx.env, deps());
    assert.equal(sent[0].headers["apns-push-type"], "background");
    assert.equal(sent[0].headers["apns-priority"], "5");
    assert.deepEqual(JSON.parse(sent[0].body), { aps: { "content-available": 1 } });
  });

  test("uses Apple's sandbox for a development device", async () => {
    const { body } = await register({ environment: "development" });
    await handle(post(`/v1/devices/${body.device_id}/wake`, {}, { Authorization: `Bearer ${body.secret}` }), ctx.env, deps());
    assert.ok(sent[0].url.startsWith("https://api.sandbox.push.apple.com/"));
  });

  test("needs the device's own secret", async () => {
    const { id } = await registered();
    for (const headers of [{}, { Authorization: "Bearer wrong" }, { Authorization: "Basic abc" }]) {
      const r = await handle(post(`/v1/devices/${id}/wake`, {}, headers), ctx.env, deps());
      assert.equal(r.status, 401);
    }
    const unknown = await handle(post("/v1/devices/doesnotexist1/wake", {}, { Authorization: "Bearer x" }), ctx.env, deps());
    assert.equal(unknown.status, 401);
    assert.equal(sent.length, 0);
  });

  test("refuses a kind or collapse id it does not know", async () => {
    const { id, auth } = await registered();
    assert.equal((await handle(post(`/v1/devices/${id}/wake`, { kind: "loud" }, auth), ctx.env, deps())).status, 400);
    assert.equal((await handle(post(`/v1/devices/${id}/wake`, { collapse_id: "a b" }, auth), ctx.env, deps())).status, 400);
    assert.equal(sent.length, 0);
  });

  test("is limited per device", async () => {
    const { id, auth } = await registered();
    ctx.env.WAKE_LIMIT = limiter(() => false);
    const r = await handle(post(`/v1/devices/${id}/wake`, {}, auth), ctx.env, deps());
    assert.equal(r.status, 429);
    assert.deepEqual(ctx.env.WAKE_LIMIT.calls, [id]);
    assert.equal(sent.length, 0);
  });

  test("forgets a device Apple says is gone", async () => {
    const { id, auth } = await registered();
    appleStatus = 410;
    appleBody = { reason: "Unregistered" };
    const r = await handle(post(`/v1/devices/${id}/wake`, {}, auth), ctx.env, deps());
    assert.equal(r.status, 410);
    assert.equal(await ctx.env.DEVICES.get(`d:${id}`), null);
    assert.equal(ctx.env.DEVICES.map.size, 0);
  });

  test("reports another Apple failure without forgetting the device", async () => {
    const { id, auth } = await registered();
    appleStatus = 503;
    const r = await handle(post(`/v1/devices/${id}/wake`, {}, auth), ctx.env, deps());
    assert.equal(r.status, 502);
    assert.notEqual(await ctx.env.DEVICES.get(`d:${id}`), null);
  });
});

describe("removing a device", () => {
  test("needs the secret and deletes both records", async () => {
    const { body } = await register();
    const url = `https://relay.test/v1/devices/${body.device_id}`;
    assert.equal((await handle(new Request(url, { method: "DELETE" }), ctx.env, deps())).status, 401);
    const r = await handle(new Request(url, { method: "DELETE", headers: { Authorization: `Bearer ${body.secret}` } }), ctx.env, deps());
    assert.equal(r.status, 200);
    assert.equal(ctx.env.DEVICES.map.size, 0);
  });
});

describe("routing", () => {
  test("answers health checks, wrong methods and unknown paths", async () => {
    assert.equal((await handle(new Request("https://relay.test/healthz"), ctx.env, deps())).status, 200);
    assert.equal((await handle(new Request("https://relay.test/v1/devices"), ctx.env, deps())).status, 405);
    assert.equal((await handle(new Request("https://relay.test/v1/devices/abcdefgh/wake"), ctx.env, deps())).status, 405);
    assert.equal((await handle(new Request("https://relay.test/nope"), ctx.env, deps())).status, 404);
  });
});

describe("Apple's provider token", () => {
  test("is an ES256 JWT for the team and key, signed so the public key verifies it, and reused until near its end", async () => {
    const now = Date.UTC(2026, 10, 6);
    const jwt = await apnsJwt(ctx.env, now);
    const [head, claims, signature] = jwt.split(".");
    const decode = (s) => JSON.parse(Buffer.from(s, "base64url").toString());
    assert.deepEqual(decode(head), { alg: "ES256", kid: ISSUER.id });
    assert.deepEqual(decode(claims), { iss: ISSUER.team, iat: Math.floor(now / 1000) });
    const ok = await webcrypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, ctx.publicKey, Buffer.from(signature, "base64url"),
      new TextEncoder().encode(`${head}.${claims}`));
    assert.equal(ok, true);
    assert.equal(await apnsJwt(ctx.env, now + 30 * 60 * 1000), jwt);
    assert.notEqual(await apnsJwt(ctx.env, now + 50 * 60 * 1000), jwt);
  });
});
