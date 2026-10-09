import { createHmac, randomBytes, webcrypto } from "node:crypto";
import { vi } from "vitest";

export type Behaviour = {
  deviceCheck?: boolean;
  prfOnCreate?: "enabled" | "results" | "none";
  attachment?: "platform" | "cross-platform";
  capabilityPrf?: boolean;
  failCreate?: string;
  failGet?: string;
  noPrfOnGet?: boolean;
  forgetCredentials?: boolean;
};

const b64 = (b: Uint8Array | ArrayBuffer) => Buffer.from(b instanceof Uint8Array ? b : new Uint8Array(b)).toString("base64");

export function installDevice(behaviour: Behaviour = {}) {
  const b: Behaviour = { deviceCheck: true, prfOnCreate: "enabled", attachment: "platform", ...behaviour };
  const files = new Map<string, Uint8Array>();
  const writes: { url: string; bytes: Uint8Array }[] = [];
  const calls = { create: 0, get: 0, deleted: 0 };
  const secrets = new Map<string, Buffer>();
  const prfOutputs: Buffer[] = [];

  const prfFor = (id: Uint8Array, input: BufferSource) => {
    const key = b64(id);
    const secret = secrets.get(key) as Buffer;
    const bytes = ArrayBuffer.isView(input) ? new Uint8Array(input.buffer, input.byteOffset, input.byteLength) : new Uint8Array(input);
    const out = createHmac("sha256", secret).update(bytes).digest();
    prfOutputs.push(out);
    return new Uint8Array(out).buffer;
  };

  const credential = (id: Uint8Array, prf: Record<string, unknown>) => ({
    rawId: new Uint8Array(id).buffer,
    authenticatorAttachment: b.attachment,
    getClientExtensionResults: () => ({ prf }),
  });

  const credentials = {
    create: vi.fn(async (o: CredentialCreationOptions): Promise<unknown> => {
      calls.create++;
      if (b.failCreate) throw new DOMException("no", b.failCreate);
      const id = new Uint8Array(randomBytes(32));
      secrets.set(b64(id), randomBytes(32));
      const input = (o.publicKey as { extensions: { prf: { eval: { first: BufferSource } } } }).extensions.prf.eval.first;
      if (b.prfOnCreate === "none") return credential(id, {});
      if (b.prfOnCreate === "results") return credential(id, { enabled: true, results: { first: prfFor(id, input) } });
      return credential(id, { enabled: true });
    }),
    get: vi.fn(async (o: CredentialRequestOptions): Promise<unknown> => {
      calls.get++;
      if (b.failGet) throw new DOMException("no", b.failGet);
      const wanted = (o.publicKey as { allowCredentials: { id: BufferSource }[] }).allowCredentials[0].id;
      const id = new Uint8Array(wanted as ArrayBuffer);
      if (b.forgetCredentials || !secrets.has(b64(id))) throw new DOMException("no", "NotAllowedError");
      if (b.noPrfOnGet) return credential(id, {});
      const input = (o.publicKey as { extensions: { prf: { eval: { first: BufferSource } } } }).extensions.prf.eval.first;
      return credential(id, { results: { first: prfFor(id, input) } });
    }),
  };

  const cache = {
    match: async (url: string) => {
      const bytes = files.get(url);
      return bytes ? new Response(bytes.slice()) : undefined;
    },
    put: async (url: string, response: Response) => {
      const bytes = new Uint8Array(await response.arrayBuffer());
      writes.push({ url, bytes });
      files.set(url, bytes);
    },
  };
  const cache2 = Object.assign(cache, { delete: async (url: string) => files.delete(url) });
  const cacheStorage = {
    open: vi.fn(async () => cache2),
    delete: vi.fn(async () => { calls.deleted++; files.clear(); return true; }),
  };

  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("caches", cacheStorage);
  vi.stubGlobal("PublicKeyCredential", {
    isUserVerifyingPlatformAuthenticatorAvailable: async () => b.deviceCheck,
    getClientCapabilities: async () => (b.capabilityPrf === undefined ? {} : { "extension:prf": b.capabilityPrf }),
  });
  Object.defineProperty(navigator, "credentials", { value: credentials, configurable: true });

  const text = () => [...files.values()].map((f) => Buffer.from(f).toString("utf8"));
  const fields = (url: string) => JSON.parse(Buffer.from(files.get(url) as Uint8Array).toString("utf8")) as Record<string, unknown>;
  const decoded = () => {
    const out: Buffer[] = [];
    const walk = (v: unknown) => {
      if (typeof v === "string") { try { out.push(Buffer.from(v, "base64")); } catch { return; } }
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    for (const url of files.keys()) walk(fields(url));
    return out;
  };
  const appears = (needle: Uint8Array | string) => {
    const n = Buffer.from(needle);
    return [...files.values()].some((f) => Buffer.from(f).includes(n)) || decoded().some((d) => d.includes(n)) || text().some((t) => t.includes(n.toString("base64")));
  };

  return { b, files, writes, calls, credentials, cacheStorage, prfOutputs, secrets, text, fields, appears };
}

export type Device = ReturnType<typeof installDevice>;
