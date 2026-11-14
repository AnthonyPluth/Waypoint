import { toast } from "svelte-sonner";
import { actGet, errMsg } from "./act";
import type { Person, PhotoGrantPerson, PhotoSharing, Trip, TripPhoto } from "./api-types";
import { apiCall } from "./contract";
import { isStale, narrowedToast, photosOf, photosTitle, removedToast, sharedWith, shareAllBody, shareBody, stateOf, unsharedOf, whoIs, type Scope, type Who } from "./photo-sharing";

export const OUT_OF_DATE_HERE = "Couldn’t refresh your photo sharing for this trip, so what shows may be out of date.";
export const NOT_LOADED_HERE = "Couldn’t load your photo sharing for this trip.";

export type Mode = "none" | "prompt" | "reminder" | "card";

export type Asking =
  | { kind: "widen"; sharing: PhotoSharing; note: string }
  | { kind: "all"; person: PhotoGrantPerson; photos: number | null; note: string }
  | { kind: "stop" };

type Hooks = { changed: () => Promise<unknown>; dropped?: (ids: number[]) => void };

const statusOf = (err: unknown): unknown => (err as { status?: unknown } | null)?.status;

const grantsOf = (): Promise<{ people: PhotoGrantPerson[] }> => apiCall<"GET /api/photo-grants">("/api/photo-grants", { keep: true });

export async function actingPersons(trip: Trip, people: Person[], me: number | null): Promise<number[] | null> {
  if (me === null) return [];
  const minors = trip.people.filter((id) => id !== me && people.find((p) => p.id === id)?.member === false);
  if (!minors.length) return [me];
  try {
    const found = (await grantsOf()).people.map((p) => p.person_id);
    return [me, ...minors.filter((id) => found.includes(id))];
  } catch {
    return null;
  }
}

export class PersonSharing {
  sharing = $state<PhotoSharing | null>(null);
  problem = $state("");
  off = $state(false);
  busy = $state(false);
  scope = $state<Scope>("only_me");
  pending = $state<Scope | null>(null);
  note = $state("");
  reopened = $state(false);
  asking = $state<Asking | null>(null);
  dialog = $state(false);
  removedOpen = $state(false);
  opener: HTMLElement | null = null;
  private ticket = 0;
  private freed: (() => void)[] = [];
  private gone = false;
  who = $state<Who>(whoIs(-1, null, []));

  constructor(readonly tripId: number, readonly personId: number, me: number | null, people: Person[], private hooks: Hooks, public tripName = "this trip") {
    this.relabel(me, people);
  }

  relabel(me: number | null, people: Person[], tripName = this.tripName): void {
    this.who = whoIs(this.personId, me, people);
    this.tripName = tripName;
  }

  readonly mode = $derived.by((): Mode => {
    const s = this.sharing;
    if (!s) return "none";
    if (s.state === "ask") return "prompt";
    if (s.state === "declined") return this.reopened ? "prompt" : s.count === 0 ? "none" : "reminder";
    if (s.state === "shared") return "card";
    return "none";
  });
  readonly outOfDate = $derived(this.sharing !== null && this.problem !== "");
  readonly locked = $derived(this.busy || this.outOfDate);
  readonly visible = $derived(!this.off && (this.mode !== "none" || this.problem !== ""));
  get title(): string { return photosTitle(this.who); }

  dispose(): void {
    this.gone = true;
    this.ticket += 1;
  }

  async load(): Promise<boolean> {
    const mine = ++this.ticket;
    try {
      const found = await stateOf(this.personId, this.tripId);
      if (mine !== this.ticket) return true;
      this.sharing = found;
      this.problem = "";
      this.off = false;
      if (found.state !== "declined") this.reopened = false;
      return true;
    } catch (err) {
      if (mine !== this.ticket) return false;
      if (statusOf(err) === 404) { this.off = true; this.sharing = null; this.problem = ""; return false; }
      this.problem = errMsg(err);
      return false;
    }
  }

  private async hold<T>(fn: () => Promise<T>): Promise<T> {
    this.busy = true;
    try { return await fn(); }
    finally {
      this.busy = false;
      for (const wake of this.freed.splice(0)) wake();
    }
  }

  private async free(): Promise<void> {
    while (this.busy) await new Promise<void>((wake) => this.freed.push(wake));
  }

  private settle(reply: PhotoSharing, mine: number): void {
    if (mine !== this.ticket || this.gone) return;
    this.sharing = reply;
    this.problem = "";
    this.off = false;
    if (reply.removed_count === 0) this.removedOpen = false;
  }

  private async afterChange(): Promise<boolean> {
    const [reloaded] = await Promise.all([this.load(), this.hooks.changed()]);
    return reloaded;
  }

  retry = (): Promise<void> => this.hold(async () => { await Promise.all([this.load(), this.hooks.changed()]); });

  setDialog = (open: boolean): void => {
    this.dialog = open;
    if (!open) this.pending = null;
  };

  reopen = (): Promise<void> => this.hold(async () => {
    const ok = await this.load();
    if (ok && this.sharing?.state === "declined") this.reopened = true;
  });

  share = (): Promise<void> => this.hold(() => this.grantHere());

  private async grantHere(): Promise<void> {
    const shown = this.sharing;
    const scope = this.scope;
    if (!shown || (scope === "trip" && shown.count === null)) return;
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing`, { method: "POST", body: shareBody(this.personId, shown, scope), failed: "Couldn’t share it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return; }
      this.note = errMsg(err);
      await this.load();
      return;
    }
    this.note = "";
    this.reopened = false;
    toast.success(`Shared with ${sharedWith(scope, this.who)}. Change it any time under ${photosTitle(this.who)}.`);
    await this.afterChange();
  }

  private async unlessStillOut(reloaded: boolean): Promise<void> {
    const s = this.sharing;
    if (!reloaded || !s || s.state === "shared" || s.state === "none") return;
    this.note = `${this.who.mine ? "Your" : `${this.who.first}’s`} other trips are shared, but this one still isn’t. Press Share on this trip to share it.`;
    if (s.state === "declined") this.reopened = true;
  }

  notNow = (): Promise<void> => this.hold(async () => {
    this.note = "";
    if (this.sharing?.state === "declined") { this.reopened = false; return; }
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing`, { method: "POST", body: { person_id: this.personId, declined: true }, failed: "Couldn’t save it" });
    } catch (err) {
      toast.error(errMsg(err));
      return;
    }
    await this.load();
  });

  private async everyone(): Promise<PhotoGrantPerson | null> {
    const found = await actGet(grantsOf);
    return found?.people.find((p) => p.person_id === this.personId) ?? null;
  }

  private askAll(person: PhotoGrantPerson, note: string): void {
    this.asking = { kind: "all", person, photos: photosOf(unsharedOf(person)), note };
    this.dialog = true;
  }

  shareAll = (e?: Event): Promise<void> => this.hold(async () => {
    this.opener = (e?.currentTarget as HTMLElement | null | undefined) ?? this.opener;
    const person = await this.everyone();
    if (!person) return;
    if (person.prefs.share_all) { await this.grantHere(); return; }
    if (this.scope === "only_me") {
      try {
        await apiCall<"POST /api/photo-sharing-prefs/{id}">(`/api/photo-sharing-prefs/${this.personId}`, { method: "POST", body: { default_scope: "only_me", share_all: true }, failed: "Couldn’t turn it on" });
      } catch (err) {
        toast.error(errMsg(err));
        return;
      }
      this.reopened = false;
      toast.success(`Sharing on all trips, with ${sharedWith("only_me", this.who).replace(" only", "")} only. Change it any time in Settings.`);
      await this.unlessStillOut(await this.afterChange());
      return;
    }
    this.askAll(person, "");
  });

  confirmAll = (): Promise<boolean> => this.hold(async () => {
    const a = this.asking;
    if (a?.kind !== "all" || (a.photos === null && a.person.eligible.length > 0)) return false;
    try {
      await apiCall<"POST /api/photo-sharing-prefs/{id}">(`/api/photo-sharing-prefs/${this.personId}`, { method: "POST", body: shareAllBody(a.person, "trip"), failed: "Couldn’t turn it on" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return false; }
      const fresh = await this.everyone();
      if (fresh) this.askAll(fresh, errMsg(err)); else this.dialog = false;
      return false;
    }
    this.reopened = false;
    toast.success("Saved");
    await this.unlessStillOut(await this.afterChange());
    return true;
  });

  choose = (next: Scope, e: Event): Promise<void> | void => {
    this.opener = e.currentTarget as HTMLElement;
    this.pending = next;
    return next === "trip" ? this.widen() : this.narrow();
  };

  private widen = (note = ""): Promise<void> => this.hold(async () => {
    const fresh = await actGet(() => stateOf(this.personId, this.tripId));
    if (!fresh) { this.pending = null; return; }
    this.asking = { kind: "widen", sharing: fresh, note };
    this.dialog = true;
  });

  confirmWiden = (): Promise<boolean> => this.hold(async () => {
    const a = this.asking;
    if (a?.kind !== "widen" || a.sharing.count === null) return false;
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing`, { method: "POST", body: shareBody(this.personId, a.sharing, "trip"), failed: "Couldn’t share it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return false; }
      const note = errMsg(err);
      const fresh = await actGet(() => stateOf(this.personId, this.tripId));
      if (fresh) this.asking = { kind: "widen", sharing: fresh, note }; else this.dialog = false;
      return false;
    }
    toast.success("Shared with everyone on this trip");
    await this.afterChange();
    return true;
  });

  private narrow = (): Promise<void> => this.hold(async () => {
    try {
      const reply = await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing`, { method: "POST", body: { person_id: this.personId, scope: "only_me" }, failed: "Couldn’t change it" });
      toast(narrowedToast(this.who, "this trip"), { action: { label: "Undo", onClick: () => { void this.undo(reply); } } });
      await this.afterChange();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      this.pending = null;
    }
  });

  private undo = (narrowed: PhotoSharing): Promise<void> => this.hold(async () => {
    try {
      await apiCall<"POST /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing`, { method: "POST", body: shareBody(this.personId, narrowed, "trip"), failed: "Couldn’t undo it" });
    } catch (err) {
      if (!isStale(err)) { toast.error(errMsg(err)); return; }
      if (this.gone) return;
      const note = errMsg(err);
      const fresh = await actGet(() => stateOf(this.personId, this.tripId));
      if (fresh) { this.opener = null; this.asking = { kind: "widen", sharing: fresh, note }; this.dialog = true; }
      return;
    }
    if (!this.gone) await this.afterChange();
  });

  askStop = (e: Event): void => {
    this.opener = e.currentTarget as HTMLElement;
    this.asking = { kind: "stop" };
    this.dialog = true;
  };

  confirmStop = (): Promise<boolean> => this.hold(async () => {
    try {
      await apiCall<"DELETE /api/trips/{id}/photo-sharing">(`/api/trips/${this.tripId}/photo-sharing?person_id=${this.personId}`, { method: "DELETE", failed: "Couldn’t stop sharing" });
    } catch (err) {
      toast.error(errMsg(err));
      return false;
    }
    await this.afterChange();
    return true;
  });

  remove = (ids: number[]): Promise<boolean> => this.hold(() => this.removeNow(ids));

  private async removeNow(ids: number[]): Promise<boolean> {
    const mine = ++this.ticket;
    let reply: PhotoSharing;
    try {
      reply = await apiCall<"POST /api/trips/{id}/photo-exclusions">(`/api/trips/${this.tripId}/photo-exclusions`, { method: "POST", body: { photo_ids: ids }, failed: "Couldn’t remove it" });
    } catch (err) {
      toast.error(errMsg(err));
      if (statusOf(err) === 404 && !this.gone) await this.afterChange();
      return false;
    }
    this.settle(reply, mine);
    if (!this.gone) this.hooks.dropped?.(ids);
    const stamps = new Map(reply.removed.map((p) => [p.id, p.removed_at]));
    toast(removedToast(this.who, ids.length, this.tripName), { action: { label: "Undo", onClick: () => { void this.undoRemoval(ids.map((id) => ({ id, created: stamps.get(id) ?? null }))); } } });
    if (!this.gone) await this.afterChange();
    return true;
  }

  private undoRemoval = async (removed: { id: number; created: number | null }[]): Promise<void> => {
    await this.free();
    await this.hold(async () => {
      let done = 0;
      for (const { id, created } of removed) {
        try {
          await this.putBackRequest(id, created);
          done++;
        } catch (err) {
          toast.error(isStale(err) ? errMsg(err) : `${errMsg(err)}${removed.length > 1 ? ` ${done} of ${removed.length} are back.` : ""}`);
          break;
        }
      }
      if (!this.gone) await this.afterChange();
    });
  };

  private putBackRequest(id: number, created: number | null): Promise<PhotoSharing> {
    const stamp = created === null ? "" : `?created=${encodeURIComponent(String(created))}`;
    return apiCall<"DELETE /api/trips/{id}/photo-exclusions/{id}">(`/api/trips/${this.tripId}/photo-exclusions/${id}${stamp}`, { method: "DELETE", failed: "Couldn’t put it back" });
  }

  putBack = (photo: TripPhoto): Promise<boolean> => this.hold(async () => {
    const mine = ++this.ticket;
    let reply: PhotoSharing;
    try {
      reply = await this.putBackRequest(photo.id, photo.removed_at);
    } catch (err) {
      toast.error(errMsg(err));
      if ((isStale(err) || statusOf(err) === 404) && !this.gone) await this.afterChange();
      return false;
    }
    this.settle(reply, mine);
    if (!this.gone) await this.afterChange();
    return true;
  });
}
