const CACHE_NAME = "waypoint-offline-vault-v1";
const KEYS_URL = "/offline-vault/keys";
const TRIP_URL = "/offline-vault/trip";
const VERSION = 1;
const IDLE_MS = 5 * 60 * 1000;
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "touchstart", "scroll"] as const;

const text = (s: string) => new TextEncoder().encode(s);
const PRF_INPUT = text("waypoint-offline-vault/v1/prf-input");
const WRAP_SALT = text("waypoint-offline-vault/v1/wrap-salt");
const WRAP_INFO = text("waypoint-offline-vault/v1/wrap-key");
const WRAP_AAD = text("waypoint-offline-vault/v1/wrapped-private-key");
const SAVE_INFO = text("waypoint-offline-vault/v1/save-key");
const SAVE_AAD = text("waypoint-offline-vault/v1/saved-trip");

const CURVE = { name: "ECDH", namedCurve: "P-256" } as const;

export const WHY_BROWSER = "This browser can’t keep an encrypted copy on the device, so nothing is saved for offline use.";
export const WHY_DEVICE = "This device can’t make a passkey that works offline (it needs Face ID, Touch ID, a fingerprint reader, Windows Hello or a screen lock that supports passkeys), so nothing is saved for offline use.";
const GONE = "The passkey for the saved trip is gone from this device.";
const CANCELLED = "The device check was cancelled.";
const DAMAGED = "The saved copy on this device can’t be read.";

export type VaultErrorCode = "unsupported" | "not-set-up" | "already-set-up" | "cancelled" | "passkey-missing" | "damaged" | "failed";

export class VaultError extends Error {
  code: VaultErrorCode;
  constructor(code: VaultErrorCode, message: string) {
    super(message);
    this.code = code;
  }
}

export type Support = { ok: true } | { ok: false; reason: string };

type Sealed = { iv: string; data: string };
type StoredKeys = { v: number; credentialId: string; publicKey: string; wrappedKey: Sealed };
type StoredTrip = { v: number; ephemeralPublicKey: string; iv: string; data: string };

type Bytes = Uint8Array<ArrayBuffer>;

function random(n: number): Bytes {
  return crypto.getRandomValues(new Uint8Array(n));
}

function toBase64(b: Uint8Array): string {
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s);
}

function fromBase64(s: string): Bytes {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function join(...parts: Uint8Array[]): Bytes {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

const sameBytes = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((x, i) => x === b[i]);

let privateKey: CryptoKey | null = null;
let idleTimer: ReturnType<typeof setTimeout> | null = null;
let lastActivity = 0;
const lockListeners = new Set<() => void>();

export function isUnlocked(): boolean {
  return privateKey !== null;
}

export function onLock(fn: () => void): () => void {
  lockListeners.add(fn);
  return () => lockListeners.delete(fn);
}

function noteActivity(): void {
  if (!privateKey) return;
  lastActivity = Date.now();
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(lock, IDLE_MS);
}

function lockIfIdle(): void {
  if (document.visibilityState === "visible" && privateKey && Date.now() - lastActivity >= IDLE_MS) lock();
}

export function lock(): void {
  const was = privateKey !== null;
  privateKey = null;
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = null;
  for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, noteActivity, true);
  document.removeEventListener("visibilitychange", lockIfIdle);
  window.removeEventListener("pagehide", lock);
  if (was) lockListeners.forEach((fn) => fn());
}

function keep(key: CryptoKey): void {
  privateKey = key;
  for (const name of ACTIVITY_EVENTS) window.addEventListener(name, noteActivity, { capture: true, passive: true });
  document.addEventListener("visibilitychange", lockIfIdle);
  window.addEventListener("pagehide", lock);
  noteActivity();
}

async function read<T>(url: string): Promise<T | null> {
  if (typeof caches === "undefined") return null;
  const hit = await (await caches.open(CACHE_NAME)).match(url);
  if (!hit) return null;
  try { return (await hit.json()) as T; } catch { throw new VaultError("damaged", DAMAGED); }
}

async function write(url: string, value: unknown): Promise<void> {
  await (await caches.open(CACHE_NAME)).put(url, new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }));
}

const isText = (x: unknown): x is string => typeof x === "string";

function validKeys(x: StoredKeys | null): StoredKeys | null {
  if (x === null) return null;
  if (x.v !== VERSION || !isText(x.credentialId) || !isText(x.publicKey) || !x.wrappedKey || !isText(x.wrappedKey.iv) || !isText(x.wrappedKey.data)) {
    throw new VaultError("damaged", DAMAGED);
  }
  return x;
}

function validTrip(x: StoredTrip | null): StoredTrip | null {
  if (x === null) return null;
  if (x.v !== VERSION || !isText(x.ephemeralPublicKey) || !isText(x.iv) || !isText(x.data)) throw new VaultError("damaged", DAMAGED);
  return x;
}

const storedKeys = async () => validKeys(await read<StoredKeys>(KEYS_URL));

export async function isSetUp(): Promise<boolean> {
  return (await storedKeys()) !== null;
}

export async function hasSavedTrip(): Promise<boolean> {
  return (await isSetUp()) && validTrip(await read<StoredTrip>(TRIP_URL)) !== null;
}

export async function support(): Promise<Support> {
  try {
    if (!window.isSecureContext || !crypto?.subtle || typeof caches === "undefined" || !navigator.credentials || typeof PublicKeyCredential === "undefined") {
      return { ok: false, reason: WHY_BROWSER };
    }
    if (!(await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable())) return { ok: false, reason: WHY_DEVICE };
    const capabilities = await PublicKeyCredential.getClientCapabilities?.();
    if (capabilities && capabilities["extension:prf"] === false) return { ok: false, reason: WHY_DEVICE };
    return { ok: true };
  } catch {
    return { ok: false, reason: WHY_DEVICE };
  }
}

function authenticatorError(e: unknown, creating: boolean): VaultError {
  const name = (e as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "AbortError") return new VaultError("cancelled", CANCELLED);
  if (creating && name === "NotSupportedError") return new VaultError("unsupported", WHY_DEVICE);
  if (!creating && (name === "InvalidStateError" || name === "NotFoundError")) return new VaultError("passkey-missing", GONE);
  return new VaultError("failed", "The device check didn’t work.");
}

function prfOutput(credential: PublicKeyCredential): Bytes | null {
  const first = credential.getClientExtensionResults().prf?.results?.first;
  if (!first) return null;
  const view = ArrayBuffer.isView(first) ? new Uint8Array(first.buffer, first.byteOffset, first.byteLength) : new Uint8Array(first);
  return view.length === 32 ? new Uint8Array(view) : null;
}

async function assertWithPrf(credentialId: Bytes): Promise<Bytes> {
  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.get({
      publicKey: {
        challenge: random(32),
        allowCredentials: [{ type: "public-key", id: credentialId, transports: ["internal"] }],
        userVerification: "required",
        timeout: 60_000,
        extensions: { prf: { eval: { first: PRF_INPUT } } },
      },
    })) as PublicKeyCredential | null;
  } catch (e) { throw authenticatorError(e, false); }
  if (!credential) throw new VaultError("cancelled", CANCELLED);
  if (!sameBytes(new Uint8Array(credential.rawId), credentialId)) throw new VaultError("passkey-missing", GONE);
  const secret = prfOutput(credential);
  if (!secret) throw new VaultError("passkey-missing", "The passkey for the saved trip can’t unlock it any more.");
  return secret;
}

async function wrapKeyFrom(secret: Bytes, usage: "encrypt" | "decrypt"): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", secret, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: WRAP_SALT, info: WRAP_INFO }, base, { name: "AES-GCM", length: 256 }, false, [usage]);
}

async function createPasskey(): Promise<{ id: Bytes; secret: Bytes | null }> {
  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.create({
      publicKey: {
        rp: { name: "Waypoint" },
        user: { id: random(16), name: "Waypoint offline access", displayName: "Waypoint offline access" },
        challenge: random(32),
        pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
        authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required", residentKey: "preferred" },
        attestation: "none",
        timeout: 60_000,
        extensions: { prf: { eval: { first: PRF_INPUT } } },
      },
    })) as PublicKeyCredential | null;
  } catch (e) { throw authenticatorError(e, true); }
  if (!credential) throw new VaultError("cancelled", CANCELLED);
  const prf = credential.getClientExtensionResults().prf;
  const builtIn = credential.authenticatorAttachment !== "cross-platform";
  if (!builtIn || !(prf?.enabled || prf?.results?.first)) throw new VaultError("unsupported", WHY_DEVICE);
  return { id: new Uint8Array(credential.rawId.slice(0)), secret: prfOutput(credential) };
}

export async function setUp(): Promise<void> {
  const ok = await support();
  if (!ok.ok) throw new VaultError("unsupported", ok.reason);
  if (await isSetUp()) throw new VaultError("already-set-up", "Offline access is already set up on this device.");
  const passkey = await createPasskey();
  const secret = passkey.secret ?? (await assertWithPrf(passkey.id));
  const pair = await crypto.subtle.generateKey(CURVE, true, ["deriveBits"]);
  const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  const iv = random(12);
  let sealedKey: ArrayBuffer;
  try {
    sealedKey = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: WRAP_AAD }, await wrapKeyFrom(secret, "encrypt"), pkcs8);
  } finally {
    pkcs8.fill(0);
    secret.fill(0);
  }
  const publicKey = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  const keys: StoredKeys = {
    v: VERSION,
    credentialId: toBase64(passkey.id),
    publicKey: toBase64(publicKey),
    wrappedKey: { iv: toBase64(iv), data: toBase64(new Uint8Array(sealedKey)) },
  };
  try { await write(KEYS_URL, keys); } catch { throw new VaultError("failed", "Couldn’t keep the key on this device."); }
}

async function saveKey(shared: ArrayBuffer, ephemeralPublic: Bytes, recipientPublic: Bytes, usage: "encrypt" | "decrypt"): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt: ephemeralPublic, info: join(SAVE_INFO, recipientPublic) },
    base, { name: "AES-GCM", length: 256 }, false, [usage],
  );
}

export async function save(value: unknown): Promise<boolean> {
  const keys = await storedKeys();
  if (!keys) return false;
  const recipientPublic = fromBase64(keys.publicKey);
  const recipient = await crypto.subtle.importKey("raw", recipientPublic, CURVE, false, []);
  const ephemeral = await crypto.subtle.generateKey(CURVE, false, ["deriveBits"]);
  const ephemeralPublic = new Uint8Array(await crypto.subtle.exportKey("raw", ephemeral.publicKey));
  const shared = await crypto.subtle.deriveBits({ name: "ECDH", public: recipient }, ephemeral.privateKey, 256);
  const aes = await saveKey(shared, ephemeralPublic, recipientPublic, "encrypt");
  const iv = random(12);
  const sealed = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: SAVE_AAD }, aes, text(JSON.stringify(value)));
  const stored: StoredTrip = { v: VERSION, ephemeralPublicKey: toBase64(ephemeralPublic), iv: toBase64(iv), data: toBase64(new Uint8Array(sealed)) };
  await write(TRIP_URL, stored);
  return true;
}

async function unwrapPrivateKey(keys: StoredKeys): Promise<CryptoKey> {
  const secret = await assertWithPrf(fromBase64(keys.credentialId));
  try {
    const wrap = await wrapKeyFrom(secret, "decrypt");
    const pkcs8 = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(keys.wrappedKey.iv), additionalData: WRAP_AAD }, wrap, fromBase64(keys.wrappedKey.data));
    try {
      return await crypto.subtle.importKey("pkcs8", pkcs8, CURVE, false, ["deriveBits"]);
    } finally {
      new Uint8Array(pkcs8).fill(0);
    }
  } catch {
    throw new VaultError("passkey-missing", "The passkey for the saved trip can’t unlock it any more.");
  } finally {
    secret.fill(0);
  }
}

async function decrypt(key: CryptoKey, keys: StoredKeys, stored: StoredTrip): Promise<unknown> {
  try {
    const ephemeralPublic = fromBase64(stored.ephemeralPublicKey);
    const ephemeral = await crypto.subtle.importKey("raw", ephemeralPublic, CURVE, false, []);
    const shared = await crypto.subtle.deriveBits({ name: "ECDH", public: ephemeral }, key, 256);
    const aes = await saveKey(shared, ephemeralPublic, fromBase64(keys.publicKey), "decrypt");
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(stored.iv), additionalData: SAVE_AAD }, aes, fromBase64(stored.data));
    return JSON.parse(new TextDecoder().decode(plain));
  } catch {
    throw new VaultError("damaged", DAMAGED);
  }
}

export async function unlock(): Promise<unknown> {
  const keys = await storedKeys();
  if (!keys) throw new VaultError("not-set-up", "Offline access isn’t set up on this device.");
  const stored = validTrip(await read<StoredTrip>(TRIP_URL));
  if (!stored) throw new VaultError("not-set-up", "There’s no saved trip on this device.");
  const key = privateKey ?? (await unwrapPrivateKey(keys));
  const value = await decrypt(key, keys, stored);
  if (privateKey === null) keep(key);
  else noteActivity();
  return value;
}

export async function remove(): Promise<void> {
  lock();
  if (typeof caches !== "undefined") await caches.delete(CACHE_NAME);
}
