// @vitest-environment jsdom
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installDevice, type Behaviour, type Device } from "../test/webauthn";
import { hasSavedTrip, isSetUp, isUnlocked, lock, onLock, remove, save, setUp, support, unlock, VaultError, WHY_BROWSER, WHY_DEVICE } from "./offline-vault";

const CANARY = "CANARY-Hotel-Zebra-4471";
const TRIP = { id: 7, name: "Trip to Springfield", note: CANARY, segments: [{ id: 1, confirmation: "ZZ9QQ1" }] };

let device: Device;
const withDevice = (b: Behaviour = {}) => { device = installDevice(b); return device; };

beforeEach(() => { withDevice(); });
afterEach(() => {
  lock();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function failure(p: Promise<unknown>): Promise<VaultError> {
  try { await p; } catch (e) { return e as VaultError; }
  throw new Error("expected a failure");
}

async function ready() {
  await setUp();
  await save(TRIP);
}

describe("round trip", () => {
  it("encrypts, locks and unlocks again", async () => {
    await ready();
    expect(await unlock()).toEqual(TRIP);
    expect(isUnlocked()).toBe(true);
    lock();
    expect(isUnlocked()).toBe(false);
    const asked = device.calls.get;
    expect(await unlock()).toEqual(TRIP);
    expect(device.calls.get).toBe(asked + 1);
  });

  it("does not ask the authenticator again while unlocked", async () => {
    await ready();
    await unlock();
    const asked = device.calls.get;
    expect(await unlock()).toEqual(TRIP);
    expect(device.calls.get).toBe(asked);
  });

  it("replaces the saved copy and keeps one", async () => {
    await ready();
    await save({ ...TRIP, name: "Second" });
    expect((await unlock() as typeof TRIP).name).toBe("Second");
    expect(device.files.size).toBe(2);
  });

  it("takes the PRF output from the creation when the device returns it there", async () => {
    withDevice({ prfOnCreate: "results" });
    await ready();
    expect(device.calls.get).toBe(0);
    lock();
    expect(await unlock()).toEqual(TRIP);
  });

  it("derives the same secret each time", async () => {
    await ready();
    await unlock();
    lock();
    await unlock();
    expect(new Set(device.prfOutputs.map((p) => p.toString("hex"))).size).toBe(1);
  });

  it("reports what is saved", async () => {
    expect(await isSetUp()).toBe(false);
    await setUp();
    expect(await isSetUp()).toBe(true);
    expect(await hasSavedTrip()).toBe(false);
    await save(TRIP);
    expect(await hasSavedTrip()).toBe(true);
  });
});

describe("what is stored", () => {
  it("never holds the canary, a private key or a PRF output in any byte", async () => {
    const exported: Uint8Array[] = [];
    const real = webcrypto.subtle.exportKey.bind(webcrypto.subtle) as (f: string, k: unknown) => Promise<ArrayBuffer | JsonWebKey>;
    vi.spyOn(webcrypto.subtle, "exportKey").mockImplementation((async (format: string, key: unknown) => {
      const out = await real(format, key);
      if (format === "pkcs8") exported.push(new Uint8Array(out as ArrayBuffer));
      return out;
    }) as never);
    await ready();
    await unlock();
    expect(exported).toHaveLength(1);
    expect(device.files.size).toBe(2);
    expect(device.appears(CANARY)).toBe(false);
    expect(device.appears("Springfield")).toBe(false);
    expect(device.appears("ZZ9QQ1")).toBe(false);
    expect(device.appears(exported[0])).toBe(false);
    expect(device.prfOutputs.length).toBeGreaterThan(0);
    for (const prf of device.prfOutputs) expect(device.appears(prf)).toBe(false);
    for (const secret of device.secrets.values()) expect(device.appears(secret)).toBe(false);
  });

  it("writes only ciphertext, the public key, the wrapped private key, the credential id and nonces", async () => {
    await ready();
    const keys = device.fields("/offline-vault/keys");
    expect(Object.keys(keys).sort()).toEqual(["credentialId", "publicKey", "v", "wrappedKey"]);
    expect(Object.keys(keys.wrappedKey as object).sort()).toEqual(["data", "iv"]);
    const trip = device.fields("/offline-vault/trip");
    expect(Object.keys(trip).sort()).toEqual(["data", "ephemeralPublicKey", "iv", "v"]);
    expect(device.writes.map((w) => w.url).sort()).toEqual(["/offline-vault/keys", "/offline-vault/trip"]);
    expect(Buffer.from(keys.publicKey as string, "base64")).toHaveLength(65);
    expect(Buffer.from(keys.credentialId as string, "base64")).toHaveLength(32);
    expect(Buffer.from((keys.wrappedKey as { iv: string }).iv, "base64")).toHaveLength(12);
    expect(Buffer.from(trip.iv as string, "base64")).toHaveLength(12);
  });

  it("uses a fresh nonce and a fresh ephemeral key for each save", async () => {
    await ready();
    const first = device.fields("/offline-vault/trip");
    await save(TRIP);
    const second = device.fields("/offline-vault/trip");
    expect(second.iv).not.toBe(first.iv);
    expect(second.ephemeralPublicKey).not.toBe(first.ephemeralPublicKey);
    expect(second.data).not.toBe(first.data);
  });

  it("writes nothing at all when no key has been set up", async () => {
    expect(await save(TRIP)).toBe(false);
    expect(device.writes).toEqual([]);
    expect(device.files.size).toBe(0);
    expect(device.calls).toEqual({ create: 0, get: 0, deleted: 0 });
  });

  it("makes no authenticator call on an online save", async () => {
    await setUp();
    const before = { ...device.calls };
    expect(await save(TRIP)).toBe(true);
    expect(await save({ ...TRIP, name: "Again" })).toBe(true);
    expect(device.calls).toEqual(before);
    expect(device.credentials.get).toHaveBeenCalledTimes(before.get);
    expect(device.credentials.create).toHaveBeenCalledTimes(before.create);
  });

  it("asks for the device's own check and a platform passkey when it is set up", async () => {
    await setUp();
    const options = device.credentials.create.mock.calls[0][0].publicKey as PublicKeyCredentialCreationOptions;
    expect(options.authenticatorSelection).toMatchObject({ authenticatorAttachment: "platform", userVerification: "required" });
    expect(options.rp.id).toBeUndefined();
    expect(JSON.stringify(options.user)).not.toMatch(/@/);
  });

  it("asks with user verification and only the stored credential when unlocking", async () => {
    await ready();
    await unlock();
    const options = device.credentials.get.mock.calls.at(-1)?.[0]?.publicKey as PublicKeyCredentialRequestOptions;
    expect(options.userVerification).toBe("required");
    expect(options.allowCredentials).toHaveLength(1);
  });
});

describe("a wrong key", () => {
  it("fails to decrypt a copy made for another key pair", async () => {
    await ready();
    const mine = device.files.get("/offline-vault/trip") as Uint8Array;
    const kept = new Uint8Array(mine);
    await remove();
    withDevice();
    await setUp();
    device.files.set("/offline-vault/trip", kept);
    const failed = await failure(unlock());
    expect(failed.code).toBe("damaged");
    expect(isUnlocked()).toBe(false);
  });

  it("fails to unwrap with a different PRF output", async () => {
    await ready();
    const [id] = [...device.secrets.keys()];
    const other = Buffer.alloc(32, 9);
    device.secrets.set(id, other);
    const failed = await failure(unlock());
    expect(failed.code).toBe("passkey-missing");
    expect(isUnlocked()).toBe(false);
  });

  it("fails on a copy that was changed on the device", async () => {
    await ready();
    const stored = device.fields("/offline-vault/trip");
    const data = Buffer.from(stored.data as string, "base64");
    data[0] ^= 1;
    device.files.set("/offline-vault/trip", new TextEncoder().encode(JSON.stringify({ ...stored, data: data.toString("base64") })));
    expect((await failure(unlock())).code).toBe("damaged");
    expect(isUnlocked()).toBe(false);
  });

  it("says a stored entry it can't parse is damaged", async () => {
    await ready();
    device.files.set("/offline-vault/keys", new TextEncoder().encode("not json"));
    expect((await failure(isSetUp())).code).toBe("damaged");
    device.files.set("/offline-vault/keys", new TextEncoder().encode(JSON.stringify({ v: 2 })));
    expect((await failure(isSetUp())).code).toBe("damaged");
  });

  it("says a trip entry of the wrong shape is damaged", async () => {
    await ready();
    device.files.set("/offline-vault/trip", new TextEncoder().encode(JSON.stringify({ v: 1 })));
    expect((await failure(unlock())).code).toBe("damaged");
  });
});

describe("locking", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] }); });

  it("locks when the app is closed", async () => {
    await ready();
    await unlock();
    const heard = vi.fn();
    onLock(heard);
    window.dispatchEvent(new Event("pagehide"));
    expect(isUnlocked()).toBe(false);
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("locks after 5 minutes idle and not before", async () => {
    await ready();
    await unlock();
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000 - 1000);
    expect(isUnlocked()).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(isUnlocked()).toBe(false);
  });

  it("stays unlocked while the person is using the app", async () => {
    await ready();
    await unlock();
    await vi.advanceTimersByTimeAsync(4 * 60 * 1000);
    window.dispatchEvent(new Event("pointerdown"));
    await vi.advanceTimersByTimeAsync(4 * 60 * 1000);
    expect(isUnlocked()).toBe(true);
    await vi.advanceTimersByTimeAsync(60 * 1000);
    expect(isUnlocked()).toBe(false);
  });

  it("locks on return to the app when the time ran out while it was in the background", async () => {
    await ready();
    await unlock();
    vi.setSystemTime(Date.now() + 6 * 60 * 1000);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(isUnlocked()).toBe(false);
  });

  it("stops listening and forgets the key once locked", async () => {
    await ready();
    await unlock();
    lock();
    const heard = vi.fn();
    onLock(heard);
    window.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    expect(heard).not.toHaveBeenCalled();
  });

  it("lets a listener stop hearing", async () => {
    await ready();
    await unlock();
    const heard = vi.fn();
    onLock(heard)();
    lock();
    expect(heard).not.toHaveBeenCalled();
  });
});

describe("when the unlock goes wrong", () => {
  it("stays locked after a cancelled unlock and works on the next try", async () => {
    await ready();
    device.b.failGet = "NotAllowedError";
    const failed = await failure(unlock());
    expect(failed.code).toBe("cancelled");
    expect(isUnlocked()).toBe(false);
    device.b.failGet = undefined;
    expect(await unlock()).toEqual(TRIP);
  });

  it("treats an aborted check as cancelled", async () => {
    await ready();
    device.b.failGet = "AbortError";
    expect((await failure(unlock())).code).toBe("cancelled");
  });

  it("says the passkey is missing when the device has forgotten it", async () => {
    await ready();
    device.b.failGet = "InvalidStateError";
    expect((await failure(unlock())).code).toBe("passkey-missing");
    device.b.failGet = "NotFoundError";
    expect((await failure(unlock())).code).toBe("passkey-missing");
    expect(isUnlocked()).toBe(false);
  });

  it("says the passkey is missing when the assertion has no PRF output", async () => {
    await ready();
    device.b.noPrfOnGet = true;
    expect((await failure(unlock())).code).toBe("passkey-missing");
  });

  it("says the passkey is missing when the device answers with another credential", async () => {
    await ready();
    device.credentials.get.mockImplementationOnce(async () => ({
      rawId: new Uint8Array(32).buffer,
      getClientExtensionResults: () => ({ prf: { results: { first: new Uint8Array(32).buffer } } }),
    }));
    expect((await failure(unlock())).code).toBe("passkey-missing");
  });

  it("treats a null answer as cancelled and another failure as a plain failure", async () => {
    await ready();
    device.credentials.get.mockImplementationOnce(async () => null);
    expect((await failure(unlock())).code).toBe("cancelled");
    device.b.failGet = "SecurityError";
    expect((await failure(unlock())).code).toBe("failed");
  });

  it("says there is nothing to unlock when nothing was set up or saved", async () => {
    expect((await failure(unlock())).code).toBe("not-set-up");
    await setUp();
    expect((await failure(unlock())).code).toBe("not-set-up");
  });

  it("removes the saved trip and the key", async () => {
    await ready();
    await unlock();
    await remove();
    expect(isUnlocked()).toBe(false);
    expect(device.files.size).toBe(0);
    expect(await isSetUp()).toBe(false);
    expect(await save(TRIP)).toBe(false);
  });
});

describe("a device that can't do it", () => {
  it("saves nothing when the passkey has no PRF", async () => {
    withDevice({ prfOnCreate: "none" });
    const failed = await failure(setUp());
    expect(failed.code).toBe("unsupported");
    expect(failed.message).toBe(WHY_DEVICE);
    expect(device.writes).toEqual([]);
    expect(await save(TRIP)).toBe(false);
    expect(device.writes).toEqual([]);
  });

  it("refuses a passkey that isn't the device's own", async () => {
    withDevice({ attachment: "cross-platform" });
    expect((await failure(setUp())).code).toBe("unsupported");
    expect(device.writes).toEqual([]);
  });

  it("refuses a device with no built-in check, before asking for a passkey", async () => {
    withDevice({ deviceCheck: false });
    expect(await support()).toEqual({ ok: false, reason: WHY_DEVICE });
    expect((await failure(setUp())).code).toBe("unsupported");
    expect(device.calls.create).toBe(0);
    expect(device.writes).toEqual([]);
  });

  it("refuses a device that says it has no PRF", async () => {
    withDevice({ capabilityPrf: false });
    expect(await support()).toEqual({ ok: false, reason: WHY_DEVICE });
  });

  it("is fine with a device that says it has PRF", async () => {
    withDevice({ capabilityPrf: true });
    expect(await support()).toEqual({ ok: true });
  });

  it("refuses a browser without the pieces", async () => {
    vi.stubGlobal("caches", undefined);
    expect(await support()).toEqual({ ok: false, reason: WHY_BROWSER });
    vi.unstubAllGlobals();
    withDevice();
    vi.stubGlobal("isSecureContext", false);
    expect(await support()).toEqual({ ok: false, reason: WHY_BROWSER });
  });

  it("says why when the check throws", async () => {
    withDevice();
    vi.stubGlobal("PublicKeyCredential", { isUserVerifyingPlatformAuthenticatorAvailable: async () => { throw new Error("x"); } });
    expect(await support()).toEqual({ ok: false, reason: WHY_DEVICE });
  });

  it("maps a creation the device refuses", async () => {
    withDevice({ failCreate: "NotSupportedError" });
    expect((await failure(setUp())).code).toBe("unsupported");
    device.b.failCreate = "NotAllowedError";
    expect((await failure(setUp())).code).toBe("cancelled");
    device.b.failCreate = "SecurityError";
    expect((await failure(setUp())).code).toBe("failed");
    expect(device.writes).toEqual([]);
  });

  it("stores nothing when the person cancels the creation", async () => {
    withDevice({ failCreate: "NotAllowedError" });
    await failure(setUp());
    expect(device.files.size).toBe(0);
    expect(await isSetUp()).toBe(false);
  });

  it("stores nothing when the follow-up check is cancelled", async () => {
    withDevice({ failGet: "NotAllowedError" });
    expect((await failure(setUp())).code).toBe("cancelled");
    expect(device.writes).toEqual([]);
  });

  it("refuses to set up twice", async () => {
    await setUp();
    expect((await failure(setUp())).code).toBe("already-set-up");
    expect(device.calls.create).toBe(1);
  });

  it("reports a failure to keep the key", async () => {
    const real = device.cacheStorage.open.getMockImplementation() as () => Promise<unknown>;
    device.cacheStorage.open.mockImplementationOnce(real as never).mockRejectedValueOnce(new Error("full"));
    const failed = await failure(setUp());
    expect(failed.code).toBe("failed");
    expect(device.writes).toEqual([]);
  });
});
