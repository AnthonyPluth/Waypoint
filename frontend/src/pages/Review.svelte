<script lang="ts" module>
  import type { ReviewItem } from "$lib/api-types";

  export const REASONS: Record<ReviewItem["reason"], string> = {
    no_markup: "No booking details found",
    incomplete: "Some details missing",
    broken: "Couldn’t be opened",
    generic: "Read from the email",
  };

  const SECOND_LEVEL = new Set(["co", "com", "org", "net", "ac", "gov"]);

  export function providerFrom(domain: string): string {
    const labels = domain.split(".").filter(Boolean);
    const name = labels.length >= 3 && SECOND_LEVEL.has(labels.at(-2) ?? "") ? labels.at(-3) : labels.at(-2) ?? labels[0] ?? "";
    return (name ?? "").split(/[-_]/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  }

  const TITLES = new Set(["mr", "mrs", "ms", "miss", "mstr", "master", "mx", "dr", "prof", "sir", "lady"]);

  export function nameKey(name: string): string {
    const lower = name.toLowerCase();
    const [last, first] = lower.includes("/") ? lower.split("/", 2) : [null, lower];
    return `${first ?? ""} ${last ?? ""}`.split(/\W+/).filter((t) => t && !TITLES.has(t)).join(" ");
  }

  export function personFor(people: { id: number; display_name: string; legal_name: string | null; aliases: string[] }[], name: string): number | null {
    const wanted = nameKey(name);
    const found = wanted ? people.filter((p) => [p.display_name, p.legal_name ?? "", ...p.aliases].some((n) => n && nameKey(n) === wanted)) : [];
    return found.length === 1 ? found[0].id : null;
  }
</script>

<script lang="ts">
  import { tick } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { act, errMsg, ignoreFailure } from "$lib/act";
  import type { Person, Review, ReviewCandidate, ReviewMatch, SegmentBody, WhoIsThis } from "$lib/api-types";
  import { refreshState, route, setQuery } from "$lib/app.svelte";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import MessageView from "$lib/components/MessageView.svelte";
  import FlightLength from "$lib/components/FlightLength.svelte";
  import ZoneSelect from "$lib/components/ZoneSelect.svelte";
  import { Input } from "$lib/components/ui/input";
  import { Sheet } from "$lib/components/ui/sheet";
  import { amountText } from "$lib/money";
  import { carAddress, differs, DEFAULT_CURRENCY, DETAILS, KINDS as FORM_KINDS, priceOf, SAME_AS_PICKUP, SEAT_LIMIT, type Kind } from "$lib/segment-form";
  import { apiCall } from "$lib/contract";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import { toast } from "svelte-sonner";

  let review = $state<Review | null>(null);
  let people = $state<Person[]>([]);
  let loadError = $state("");

  async function load() {
    loadError = "";
    try {
      const [r, p] = await Promise.all([apiCall<"GET /api/review">("/api/review"), apiCall<"GET /api/people">("/api/people")]);
      review = r; people = p.people;
    } catch (err) { review = null; loadError = errMsg(err); }
  }
  $effect(() => { void load(); });

  const settle = async () => {
    await load();
    await refreshState().catch(ignoreFailure);
  };

  const KINDS: [string, string][] = FORM_KINDS.map(([key, name]) => [key, key === "hotel" ? "Hotel stay" : name]);
  const selectClass = "border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";

  const only = $derived.by(() => {
    const q = new URLSearchParams(route.query);
    const from = q.get("sender");
    return from ? { sender: from, mailbox: q.get("mailbox") } : null;
  });
  const shown = $derived(review ? (only ? review.items.filter((i) => i.sender_domain === only.sender && (!only.mailbox || i.address === only.mailbox)) : review.items) : []);

  const sender = (i: ReviewItem) => i.sender_domain || "Unknown sender";
  const subject = (i: ReviewItem) => i.subject || `Mail from ${sender(i).toLowerCase() === "unknown sender" ? "an unknown sender" : sender(i)}${i.received ? ` on ${i.received}` : ""}`;

  const SHOWN: Record<string, string[]> = { flight: ["flight_number", "cabin"], hotel: ["address", "phone"], car: ["phone"], train: ["address"], parking: ["address"], cruise: ["address", "phone", "room", "ship", "deck"] };
  const detailLabel = (kind: string, key: string) => DETAILS[kind as Kind].find(([k]) => k === key)?.[1] ?? key;
  type Draft = { item: ReviewItem; pick: number; suggested: boolean; kind: string; provider: string; confirmation: string; origin: string; destination: string; start: string; end: string; startZone: string; endZone: string; details: Record<string, string>; read: string[]; travelers: { name: string; seat: string }[]; sources: Record<string, string>; cost: string; currency: string; addressField: boolean };
  const detailsOf = (s: ReviewItem["suggestions"][number]): Record<string, string> => ({ address: s.address ?? "", phone: s.phone ?? "", room: s.room ?? "", ship: s.ship ?? "", deck: s.deck ?? "", flight_number: s.flight_number ?? "", cabin: s.cabin ?? "" });
  const suggestedDraft = (item: ReviewItem, s: ReviewItem["suggestions"][number], pick: number): Draft => ({
    item, pick, suggested: true, kind: s.kind, provider: s.provider ?? providerFrom(item.sender_domain), confirmation: s.confirmation ?? "", origin: s.origin,
    destination: s.destination ?? "", start: s.start_local.slice(0, 16), end: s.end_local.slice(0, 16), startZone: s.start_zone ?? "", endZone: s.end_zone ?? "", details: s.kind === "car" && s.address?.trim() === s.origin.trim() ? { ...detailsOf(s), address: "" } : detailsOf(s),
    read: Object.entries(detailsOf(s)).filter(([, v]) => v).map(([k]) => k), travelers: (s.travelers ?? []).map((t) => ({ ...t })), sources: s.sources ?? {},
    cost: s.price_minor && s.price_currency ? amountText(s.price_minor, s.price_currency) : "", currency: s.price_currency ?? DEFAULT_CURRENCY,
    addressField: s.kind === "car" && differs(s.address, s.origin) });
  const handDraft = (item: ReviewItem): Draft => ({ item, pick: 0, suggested: false, kind: "flight", provider: providerFrom(item.sender_domain), confirmation: "", origin: "", destination: "", start: "", end: "", startZone: "", endZone: "", details: {}, read: [], travelers: [], sources: {}, cost: "", currency: DEFAULT_CURRENCY, addressField: false });
  let drafts = $state<Draft[]>([]);
  let joining = $state<{ legs: Draft[]; bodies: SegmentBody[]; found: (ReviewCandidate | null)[] } | null>(null);
  const draft = $derived(drafts[0] ?? null);
  let formError = $state("");
  let saving = $state(false);
  let emailOpen = $state(true);
  let baseline = "";
  let addedIds: number[] = [];
  let addedPicks: number[] = [];
  const fingerprint = (d: Draft) => JSON.stringify([d.kind, d.provider, d.confirmation, d.origin, d.destination, d.start, d.end, d.startZone, d.endZone,
    Object.entries(d.details).filter(([, v]) => v.trim()).sort(([a], [b]) => a.localeCompare(b)), d.travelers.map((t) => [t.name, t.seat.trim()]), d.cost, d.currency]);
  const fingerprints = () => JSON.stringify(drafts.map(fingerprint));
  const dirty = $derived(drafts.length > 0 && fingerprints() !== baseline);
  const startAdd = (item: ReviewItem, use = false) => {
    if (draft && draft.item.id !== item.id) delete peeks[draft.item.id];
    emailOpen = true;
    addedIds = [];
    addedPicks = [];
    joining = null;
    drafts = use && item.suggestions.length ? item.suggestions.map((s, n) => suggestedDraft(item, s, n + 1)) : [handDraft(item)];
    baseline = fingerprints();
    formError = "";
    void peek(item);
  };
  const dropLeg = (leg: Draft) => { drafts = drafts.filter((d) => d !== leg); };
  const addedLegs = new WeakSet<Draft>();
  const addLeg = async () => {
    const last = drafts.at(-1);
    if (!last) return;
    drafts = [...drafts, { ...handDraft(last.item), kind: last.kind, provider: last.provider, confirmation: last.confirmation, origin: last.kind === "flight" ? last.destination : "" }];
    const made = drafts.at(-1);
    if (made) addedLegs.add(made);
    await tick();
    document.querySelector<HTMLElement>("[data-slot='sheet'] fieldset[data-testid='leg']:last-of-type select")?.focus();
  };
  const kindChanged = (leg: Draft, kind: string) => {
    if (!addedLegs.has(leg) || kind === leg.kind) return;
    Object.assign(leg, { kind, origin: "", destination: "", startZone: "", endZone: "", details: {}, read: [], sources: {}, addressField: false });
  };
  const plural = (n: number, ds: Draft[]) => (ds.every((d) => d.kind === "flight") ? `${n} flights` : `${n} bookings`);
  const legTitle = (leg: Draft, n: number) => `${leg.kind === "flight" ? "Flight" : "Booking"} ${n + 1} of ${drafts.length}${leg.origin && leg.destination ? `: ${leg.origin.toUpperCase()} → ${leg.destination.toUpperCase()}` : ""}`;
  type Peek = { state: "loading" } | { state: "ready"; subject: string | null; text: string; html: string | null; truncated: boolean; original: boolean; images: number } | { state: "error"; message: string };
  let peeks = $state<Record<number, Peek>>({});
  let viewing = $state<number | null>(null);
  const toggleView = (item: ReviewItem) => {
    if (viewing === item.id) { viewing = null; return; }
    viewing = item.id;
    void peek(item);
  };
  async function peek(item: ReviewItem) {
    if (peeks[item.id] && peeks[item.id]?.state !== "error") return;
    peeks[item.id] = { state: "loading" };
    try {
      const r = await apiCall<"GET /api/review/{id}/preview">(`/api/review/${item.id}/preview`);
      peeks[item.id] = { state: "ready", subject: r.subject ?? null, text: r.text, html: r.html ?? null, truncated: r.truncated, original: r.original, images: r.images };
    } catch (err) { peeks[item.id] = { state: "error", message: errMsg(err) }; }
  }

  const asking_ai = new SvelteSet<number>();
  const askAi = (item: ReviewItem) => act(async () => {
    await apiCall<"POST /api/review/{id}/suggest">(`/api/review/${item.id}/suggest`, { method: "POST" });
    await settle();
  }, { busy: (on) => (on ? asking_ai.add(item.id) : asking_ai.delete(item.id)) });

  let asking_all = $state(false);
  const unasked = $derived(review?.ai ? review.items.filter((i) => i.mine && !i.suggestions.length && !asking_ai.has(i.id)) : []);
  const askAll = (items: ReviewItem[]) => act(async () => {
    let done = 0;
    try {
      for (const item of items) {
        await apiCall<"POST /api/review/{id}/suggest">(`/api/review/${item.id}/suggest`, { method: "POST" });
        done++;
      }
    } catch (err) {
      await settle();
      throw new Error(`Asked about ${done} of ${items.length}: ${errMsg(err)}`, { cause: err });
    }
    await settle();
    toast.success(`Asked the AI about ${done} ${done === 1 ? "message" : "messages"}`);
  }, { busy: (on) => (asking_all = on) });

  const placeLabels = (kind: string) => kind === "flight" ? ["From (airport code)", "To (airport code)"] : kind === "hotel" ? ["Hotel", ""] : kind === "parking" ? ["Lot", ""] : kind === "car" ? ["Pick-up", "Drop-off"] : kind === "cruise" ? ["Embarkation port", "Disembarkation port"] : ["From (station)", "To (station)"];

  const closeForm = () => {
    const open = draft;
    const picks = addedPicks;
    addedPicks = [];
    if (open && viewing !== open.item.id) delete peeks[open.item.id];
    drafts = [];
    joining = null;
    if (open && picks.length) void act(async () => {
      await apiCall<"DELETE /api/review/{id}">(`/api/review/${open.item.id}?${picks.map((n) => `suggestion=${n}`).join("&")}`, { method: "DELETE" });
      await settle();
    });
  };
  let discarding = $state(false);
  const requestClose = () => {
    if (saving) return;
    if (dirty) discarding = true;
    else closeForm();
  };
  const focusSheet = (e: Event) => {
    e.preventDefault();
    const sheet = document.querySelector<HTMLElement>("[data-slot='sheet']");
    const target = draft?.suggested ? "[data-dialog-title]" : "form[data-editor] select";
    sheet?.querySelector<HTMLElement>(target)?.focus({ preventScroll: true });
  };

  function bodyOf(d: Draft): SegmentBody | string {
    const flight = d.kind === "flight";
    const details = Object.fromEntries((SHOWN[d.kind] ?? []).map((key) => [key, (d.details[key] ?? "").trim()] as const).filter(([, v]) => v));
    const stay = d.kind === "hotel" || d.kind === "parking";
    const pickup = carAddress(d.details["address"], d.origin, undefined);
    if (d.kind === "car" && pickup) details["address"] = pickup;
    if (d.cost.trim() && (!/^[A-Za-z]{3}$/.test(d.currency.trim()) || priceOf(d) === null)) return "Enter the cost as an amount like 1240.00 and a three-letter currency code like USD";
    if (stay && !d.startZone.trim() && !details["address"]) return `Enter the ${d.kind === "hotel" ? "hotel" : "lot"}’s time zone (for example America/New_York), or its address to work it out from`;
    return { kind: d.kind as "flight" | "hotel" | "car" | "train" | "cruise" | "parking", start_local: d.start, end_local: d.end, provider: d.provider, confirmation: d.confirmation, origin: d.origin,
      destination: d.kind === "car" && !d.destination.trim() ? d.origin : d.destination, ...(Object.keys(details).length && { details }), ...(priceOf(d) && { price: priceOf(d) }),
      ...(flight && d.travelers.length && { travelers: d.travelers.map((t) => { const id = personFor(people, t.name); return { ...(id === null ? { person_id: null, name: t.name } : { person_id: id }), seat: t.seat.trim() || null }; }) }),
      ...(flight ? {} : stay ? { start_zone: d.startZone.trim() || null } : d.kind === "cruise" ? { start_zone: d.startZone, end_zone: d.endZone || d.startZone } : { ...(d.startZone && { start_zone: d.startZone }), ...(d.endZone && { end_zone: d.endZone }) }) };
  }

  async function add(e: SubmitEvent) {
    e.preventDefault();
    const legs = [...drafts];
    const first = legs[0];
    if (!first) return;
    const bodies: SegmentBody[] = [];
    for (const leg of legs) {
      const built = bodyOf(leg);
      if (typeof built === "string") { formError = built; return; }
      bodies.push(built);
    }
    const found: (ReviewCandidate | null)[] = [];
    const checked = await act(async () => {
      for (const body of bodies) found.push((await apiCall<"POST /api/review/{id}/same">(`/api/review/${first.item.id}/same`, { method: "POST", body })).booking);
    }, { busy: (on) => (saving = on), onError: (m) => (formError = m) });
    if (!checked) return;
    if (found.some(Boolean)) { formError = ""; joining = { legs, bodies, found }; return; }
    await save(legs, bodies, found, false);
  }

  const joinSame = (attach: boolean) => {
    const open = joining;
    if (open) void save(open.legs, open.bodies, open.found, attach);
  };

  async function save(legs: Draft[], bodies: SegmentBody[], found: (ReviewCandidate | null)[], attach: boolean) {
    const first = legs[0];
    if (!first) return;
    const added = addedIds;
    const before = added.length;
    let listed = false;
    let attached = 0;
    const ok = await act(async () => {
      for (const [n, body] of bodies.entries()) {
        const same = found[n];
        if (attach && same) {
          const joined = await apiCall<"POST /api/review/{id}/attach">(`/api/review/${first.item.id}/attach`, { method: "POST", body });
          added.push(joined.segment_id);
          attached++;
        } else {
          const made = await apiCall<"POST /api/segments">("/api/segments", { method: "POST", body });
          added.push(made.id);
        }
        const leg = legs[n];
        if (leg?.pick) addedPicks.push(leg.pick);
        if (n < bodies.length - 1) drafts = drafts.filter((d) => d !== leg);
      }
      listed = true;
      await apiCall<"DELETE /api/review/{id}">(`/api/review/${first.item.id}?${added.map((id) => `segment=${id}`).join("&")}`, { method: "DELETE" });
    }, { busy: (on) => (saving = on), onError: (m) => {
      if (listed) toast.error(`Added, but couldn’t take it off this list: ${m}`);
      else formError = added.length ? `Added ${added.length} of ${before + bodies.length}, but couldn’t add the rest: ${m}` : m;
    } });
    if (!ok) { joining = null; if (listed) { closeForm(); await settle(); } else if (added.length) await settle(); return; }
    addedPicks = [];
    closeForm();
    toast.success(attached === bodies.length ? (attached > 1 ? "Added the email to your existing bookings" : "Added the email to your existing booking") : added.length > 1 ? `Added ${plural(added.length, legs)} to your trips` : "Added to your trips");
    await settle();
  }

  const dismiss = (i: ReviewItem) => act(async () => {
    await apiCall<"DELETE /api/review/{id}">(`/api/review/${i.id}`, { method: "DELETE" });
    toast.success(i.count > 1 ? `Dismissed ${i.count} emails` : "Dismissed");
    await settle();
  });

  let ignoring = $state<ReviewItem | null>(null);
  let asking = $state(false);
  const goingCount = $derived(ignoring && review ? review.items.filter((i) => i.address === ignoring?.address && i.sender_domain === ignoring?.sender_domain && !i.holds_bookings).reduce((n, i) => n + i.count, 0) : 0);
  const UNDO_MS = 8000;
  const undoIgnore = (mailboxId: number, domain: string) => act(async () => {
    await apiCall<"POST /api/mailboxes/{id}/unignore">(`/api/mailboxes/${mailboxId}/unignore`, { method: "POST", body: { domain }, failed: "Couldn’t undo that" });
    toast.success(`Reading again what was skipped from ${domain}`);
    await settle();
  });
  const ignore = (i: ReviewItem) => act(async () => {
    const r = await apiCall<"POST /api/review/{id}/ignore">(`/api/review/${i.id}/ignore`, { method: "POST" });
    toast.success(`Ignoring ${r.domain}`, {
      description: "You can undo this in Settings → Mail and AI → Gmail",
      duration: UNDO_MS,
      action: { label: "Undo", onClick: () => { void undoIgnore(r.mailbox_id, r.domain); } },
    });
    await settle();
  });

  let chosen = $state<Record<number, string>>({});
  let guestName = $state<Record<number, string>>({});
  let matching = $state<number | null>(null);
  const what = (w: Pick<WhoIsThis, "kind" | "origin" | "destination" | "start_local" | "provider">) => `${w.kind === "hotel" ? "Stay" : w.kind === "parking" ? "Parking" : w.kind === "car" ? "Rental" : w.kind === "train" ? "Train" : w.kind === "cruise" ? "Cruise" : "Flight"}${w.origin ? ` ${w.origin}${w.destination ? ` → ${w.destination}` : ""}` : ""} on ${w.start_local.slice(0, 10)}${w.provider ? ` (${w.provider})` : ""}`;

  let settling = $state<string | null>(null);
  const matchKey = (m: ReviewMatch) => `${m.item_id}-${m.entry}`;
  const settleMatch = (m: ReviewMatch, segmentId: number | null) => act(async () => {
    await apiCall<"POST /api/review/{id}/match">(`/api/review/${m.item_id}/match`, { method: "POST", body: { entry: m.entry, segment_id: segmentId } });
    toast.success(segmentId === null ? "Added to your trips" : "Filled in");
    await settle();
  }, { busy: (on) => (settling = on ? matchKey(m) : null) });
  const dismissMatch = (m: ReviewMatch) => act(async () => {
    await apiCall<"DELETE /api/review/{id}">(`/api/review/${m.item_id}?entry=${m.entry}`, { method: "DELETE" });
    toast.success("Dismissed");
    await settle();
  }, { busy: (on) => (settling = on ? matchKey(m) : null) });

  async function match(w: WhoIsThis) {
    const pick = chosen[w.id];
    if (!pick) return;
    const body = pick === "new" ? { new_guest: guestName[w.id] ?? "" } : { person_id: Number(pick) };
    const ok = await act(async () => {
      const r = await apiCall<"POST /api/review/who/{id}">(`/api/review/who/${w.id}`, { method: "POST", body });
      toast.success(r.matched > 1 ? `Matched on ${r.matched} bookings` : "Matched");
    }, { busy: (on) => (matching = on ? w.id : null) });
    if (ok) await settle();
  }
</script>

<h1 class="mb-6 text-display">Review</h1>

{#snippet detailField(d: Draft, key: string)}
  {@const outlined = !!d.sources[key] || d.read.includes(key)}
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{detailLabel(d.kind, key)} {#if d.sources[key]}<span class="font-normal text-muted-foreground">from “{d.sources[key]}”</span>{/if}</span>
    <Input class={outlined ? "ring-2 ring-primary" : ""} value={d.details[key] ?? ""} oninput={(e) => (d.details[key] = e.currentTarget.value)} maxlength={key === "address" ? 300 : 200} autocomplete="off" /></label>
{/snippet}

{#snippet legFields(d: Draft)}
  {@const labels = placeLabels(d.kind)}
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">What is it?</span>
    <select value={d.kind} onchange={(e) => { kindChanged(d, e.currentTarget.value); d.kind = e.currentTarget.value; }} class={selectClass}>{#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}</select></label>
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Provider</span>
    <Input bind:value={d.provider} maxlength={100} autocomplete="off" /></label>
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Confirmation code {#if d.sources["confirmation"]}<span class="font-normal text-muted-foreground">from “{d.sources["confirmation"]}”</span>{/if}</span>
    <Input class={d.sources["confirmation"] ? "ring-2 ring-primary" : ""} bind:value={d.confirmation} maxlength={50} autocomplete="off" spellcheck={false} /></label>
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{labels[0]} {#if d.sources["origin"]}<span class="font-normal text-muted-foreground">from “{d.sources["origin"]}”</span>{/if}</span>
    <Input class={d.sources["origin"] ? "ring-2 ring-primary" : ""} bind:value={d.origin} required maxlength={100} autocomplete="off" /></label>
  {#if labels[1]}
    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{labels[1]}</span>
      <Input bind:value={d.destination} required={d.kind === "flight"} maxlength={100} autocomplete="off" placeholder={d.kind === "car" ? SAME_AS_PICKUP : ""} /></label>
  {/if}
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{d.kind === "hotel" ? "Check-in" : d.kind === "parking" ? "Entry" : d.kind === "car" ? "Pick-up time" : "Departs"} {#if d.sources["start_local"]}<span class="font-normal text-muted-foreground">from “{d.sources["start_local"]}”</span>{/if}</span>
    <Input type="datetime-local" class={d.sources["start_local"] ? "ring-2 ring-primary" : ""} bind:value={d.start} required /></label>
  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{d.kind === "hotel" ? "Check-out" : d.kind === "parking" ? "Exit" : d.kind === "car" ? "Drop-off time" : "Arrives"} {#if d.sources["end_local"]}<span class="font-normal text-muted-foreground">from “{d.sources["end_local"]}”</span>{/if}</span>
    <Input type="datetime-local" class={d.sources["end_local"] ? "ring-2 ring-primary" : ""} bind:value={d.end} required /></label>
  {#if d.kind === "flight"}<FlightLength origin={d.origin} destination={d.destination} start={d.start} end={d.end} />{/if}
  <div class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Cost</span>
    <div class="flex gap-3">
      <Input class={`min-w-0 flex-1 ${d.cost ? "ring-2 ring-primary" : ""}`} bind:value={d.cost} inputmode="decimal" autocomplete="off" spellcheck={false} placeholder="1,240.00" aria-label="Cost amount" />
      <Input class="w-24 uppercase" bind:value={d.currency} maxlength={3} autocomplete="off" spellcheck={false} placeholder="USD" aria-label="Cost currency" />
    </div></div>
  {#if d.kind === "hotel" || d.kind === "parking"}
    {@render detailField(d, "address")}
    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone</span>
      <ZoneSelect bind:value={d.startZone} blank="Work it out from the address" /></label>
    {@render detailField(d, "phone")}
  {:else if d.kind !== "flight"}
    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone where it starts</span>
      <ZoneSelect bind:value={d.startZone} blank={d.kind === "cruise" ? "Choose a time zone" : "Work it out from the airport"} required={d.kind === "cruise"} /></label>
    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone where it ends</span>
      <ZoneSelect bind:value={d.endZone} blank="Same as where it starts" /></label>
    {#if d.kind === "car" && d.addressField}
      <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Pick-up address</span>
        <Input value={d.details["address"] ?? ""} oninput={(e) => (d.details["address"] = e.currentTarget.value)} maxlength={300} autocomplete="off" /></label>
    {/if}
    {#each SHOWN[d.kind] ?? [] as key (key)}{@render detailField(d, key)}{/each}
  {:else}
    {#each SHOWN.flight as key (key)}{#if d.read.includes(key)}{@render detailField(d, key)}{/if}{/each}
    {#if d.travelers.length}
      <div class="flex flex-col gap-1.5 text-sm" role="group" aria-label="Seats"><span class="font-medium">Seats <span class="font-normal text-muted-foreground">as the email prints them</span></span>
        {#each d.travelers as t (t.name)}
          <label class="flex items-center gap-3"><span class="min-w-0 flex-1 break-words">{t.name}</span>
            <Input class="w-24 ring-2 ring-primary" bind:value={t.seat} maxlength={SEAT_LIMIT} autocomplete="off" spellcheck={false} aria-label={`Seat for ${t.name}`} /></label>
        {/each}
      </div>
    {/if}
  {/if}
{/snippet}

{#snippet addForm(item: ReviewItem)}
  {@const lead = drafts[0]}
  {@const many = drafts.length > 1}
  <form class="flex w-full flex-col gap-4" data-editor onsubmit={add} aria-label={lead?.suggested ? (many ? "Check these suggestions" : "Check this suggestion") : "Add this booking by hand"}>
    {#if lead?.suggested && item.reason === "generic"}<p class="text-sm text-muted-foreground">Waypoint read this from labelled lines in the email, not from the vendor’s own booking data. The fields it found are outlined: check each against the booking, change what’s off, then add it. Adding it also trusts {sender(item)}, so later mail from there is added without asking.</p>
    {/if}
    {#if many}
      {#each drafts as leg, n (leg)}
        <fieldset class="flex min-w-0 flex-col gap-4 rounded-xl border border-border p-3" data-testid="leg">
          <legend class="px-1 text-sm font-medium">{legTitle(leg, n)}</legend>
          {@render legFields(leg)}
          <div><Button type="button" variant="outline" size="sm" disabled={saving} onclick={() => dropLeg(leg)} aria-label={`Dismiss ${legTitle(leg, n)}`}>Dismiss this {leg.kind === "flight" ? "flight" : "booking"}</Button></div>
        </fieldset>
      {/each}
    {:else if lead}
      {@render legFields(lead)}
    {/if}
    {#if !joining}
      <div><Button type="button" variant="outline" size="sm" disabled={saving} onclick={addLeg}>Add another leg or booking</Button></div>
    {/if}
    {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
    {#if joining}
      {@const matches = joining.found.filter((f): f is ReviewCandidate => f !== null)}
      <div class="flex flex-col gap-3 rounded-xl border border-primary p-3" role="group" aria-label="This looks like a booking you already have" data-testid="same-booking">
        <p class="text-sm font-medium">{matches.length > 1 ? "These look like bookings you already have" : "This looks like a booking you already have"}</p>
        <ul class="list-disc space-y-1 pl-5 text-sm">
          {#each matches as m (m.segment_id)}<li>{what(m)}{m.trip_name ? `, in ${m.trip_name}` : ""}</li>{/each}
        </ul>
        <p class="text-sm text-muted-foreground">The same confirmation code on the same kind of booking, around the same dates. Add this email to {matches.length > 1 ? "them" : "it"} instead of making another booking? Nothing already there is changed, only what’s missing is filled in.</p>
        <div class="flex flex-wrap gap-2">
          <Button type="button" disabled={saving} onclick={() => joinSame(true)}>{saving ? "Adding…" : matches.length > 1 ? "Add the email to those bookings" : "Add the email to that booking"}</Button>
          <Button type="button" variant="outline" disabled={saving} onclick={() => joinSame(false)}>Add as a separate booking</Button>
          <Button type="button" variant="ghost" disabled={saving} onclick={() => (joining = null)}>Go back</Button>
        </div>
      </div>
    {:else}
      <div class="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Adding…" : many ? `Add ${plural(drafts.length, drafts)}` : "Add to my trips"}</Button>
        <Button type="button" variant="outline" disabled={saving} onclick={requestClose}>Cancel</Button>
      </div>
    {/if}
  </form>
{/snippet}

{#snippet messagePeek(item: ReviewItem)}
  {@const p = peeks[item.id]}
  <div class="w-full min-w-0 space-y-2" aria-label={`The message from ${sender(item)}`} role="region">
    {#if p.state === "loading"}<p class="text-sm text-muted-foreground" role="status">Fetching the message from Gmail…</p>
    {:else if p.state === "error"}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{p.message}</p>
    {:else}
      <MessageView subject={p.subject} text={p.text} html={p.html} truncated={p.truncated} original={p.original} images={p.images} imagesAt={`/api/review/${item.id}/images/`} />
    {/if}
  </div>
{/snippet}

{#if loadError}
  <Alert><AlertDescription class="flex flex-wrap items-center justify-between gap-3">
    <span>{loadError}</span><Button variant="outline" onclick={load}>Try again</Button>
  </AlertDescription></Alert>
{:else if review === null}
  <div class="h-40 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading"></div>
{:else if review.items.length === 0 && review.who.length === 0 && review.matches.length === 0}
  <div class="flex flex-col items-start gap-3 rounded-2xl border border-dashed p-6 text-muted-foreground">
    <CircleCheck class="size-6 text-primary" aria-hidden="true" />
    <p class="max-w-prose leading-relaxed">Nothing to review. Mail Waypoint can’t read, and names on bookings it can’t match to a person, will show up here.</p>
  </div>
{:else}
  <div class="space-y-8">
    {#if review.items.length}
      <section aria-labelledby="unread-title" class="space-y-2">
        <h2 id="unread-title" class="eyebrow px-1">Couldn’t read</h2>
        <p class="px-1 text-sm text-muted-foreground">These looked like bookings, and Waypoint couldn’t get one out of them. Only you see the ones from your own mailboxes, unless someone shares theirs (Settings → Mail and AI → Gmail), and then you can add those by hand or dismiss them. Choose View email to read one here, or Add by hand to read it beside the form. Waypoint keeps each message here, encrypted, so you can read it without Gmail: until the item is dismissed or added, and for as long as a booking you add from it exists.</p>
        {#if only}
          <p class="px-1 text-sm" data-testid="review-filter">Showing only mail from {only.sender}{only.mailbox ? ` in ${only.mailbox}` : ""}{shown.length ? "" : ", and none is waiting"}. <button type="button" class="underline underline-offset-2" onclick={() => setQuery("")}>Show everything</button></p>
        {/if}
        {#if unasked.length > 1}
          <div class="px-1"><Button variant="outline" size="sm" disabled={asking_all} onclick={() => askAll(unasked)}>{asking_all ? "Asking…" : `Ask AI about all ${unasked.length}`}</Button></div>
        {/if}
        <ul class="rows" aria-label="Couldn’t read">
          {#each shown as item (item.id)}
            <li class="row items-start" data-testid="review-item">
              <div class="min-w-0 basis-full">
                <p class="break-words font-medium">{subject(item)}</p>
                <p class="break-words text-sm text-muted-foreground">{[item.received && `Sent ${item.received}`, item.mine ? `to ${item.address}` : `in ${item.owner}’s mailbox, shared with the household`].filter(Boolean).join(" · ")}</p>
                <p class="mt-1"><Badge variant="secondary">{REASONS[item.reason]}</Badge>{#if item.suggestions.length && item.reason !== "generic"} <Badge variant="outline">AI suggestion</Badge>{/if}{#if item.auto_read && item.suggestions.length && item.reason !== "generic"} <Badge variant="outline">read automatically</Badge>{/if}</p>
                {#if item.suggestion_error}<p class="mt-1 text-sm text-muted-foreground" role="status">{item.suggestion_error}</p>{/if}
                {#if item.count > 1}
                  <details class="mt-2 text-sm" data-testid="same-reservation">
                    <summary class="cursor-pointer text-muted-foreground">{item.count} emails about the same reservation</summary>
                    <ul class="mt-1 space-y-1 pl-4" aria-label="The other emails about it">
                      {#each item.others as other (other.id)}
                        <li class="break-words">{other.subject ?? `Mail from ${sender(item)}${other.received ? ` on ${other.received}` : ""}`}{other.subject && other.received ? ` · ${other.received}` : ""}</li>
                      {/each}
                    </ul>
                  </details>
                {/if}
              </div>
              <div class="flex basis-full flex-wrap gap-2">
                <Button variant="outline" size="sm" aria-expanded={viewing === item.id} onclick={() => toggleView(item)} aria-label={`View email “${subject(item)}”`}>View email</Button>
                {#if review.ai && item.mine && item.reason !== "generic"}<Button variant="outline" size="sm" disabled={asking_all || asking_ai.has(item.id)} onclick={() => askAi(item)} aria-label={`Ask AI about “${subject(item)}”`}>{asking_ai.has(item.id) ? "Asking…" : item.suggestions.length ? "Ask again" : "Ask AI"}</Button>{/if}
                {#if item.suggestions.length}<Button size="sm" onclick={() => startAdd(item, true)} aria-label={item.reason === "generic" ? `Check what Waypoint read from “${subject(item)}”` : item.suggestions.length > 1 ? `Check the AI’s ${item.suggestions.length} suggestions for “${subject(item)}”` : `Check the AI’s suggestion for “${subject(item)}”`}>{item.suggestions.length > 1 ? `Check ${item.suggestions.length} suggestions` : "Check suggestion"}</Button>{/if}
                <Button variant="outline" size="sm" onclick={() => startAdd(item)} aria-label={`Add “${subject(item)}” by hand`}>Add by hand</Button>
                {#if item.sender_domain && item.mine}<Button variant="outline" size="sm" onclick={() => { ignoring = item; asking = true; }} aria-label={`Not travel: ignore ${item.sender_domain}`}>Not travel: ignore this sender</Button>{/if}
                <Button variant="outline" size="sm" onclick={() => dismiss(item)} aria-label={item.count > 1 ? `Dismiss all ${item.count} emails about “${subject(item)}”` : `Dismiss “${subject(item)}”`}>{item.count > 1 ? "Dismiss all" : "Dismiss"}</Button>
              </div>
            </li>
            {#if viewing === item.id && peeks[item.id]}
              <li class="row items-stretch" data-testid="preview">{@render messagePeek(item)}</li>
            {/if}
          {/each}
        </ul>
      </section>
    {/if}

    {#if review.matches.length}
      <section aria-labelledby="matches-title" class="space-y-2">
        <h2 id="matches-title" class="eyebrow px-1">Could be one of your bookings</h2>
        <p class="px-1 text-sm text-muted-foreground">A booking email fits more than one of the bookings you added yourself, so Waypoint hasn’t guessed. Choose which one it is and the email fills in its confirmation code and link, or add it as a booking of its own.</p>
        <ul class="rows" aria-label="Could be one of your bookings">
          {#each review.matches as m (matchKey(m))}
            <li class="row flex-col items-stretch gap-3" data-testid="match-item">
              <div class="min-w-0">
                <p class="break-words font-medium">{what(m.booking)}{m.booking.confirmation ? ` · ${m.booking.confirmation}` : ""}</p>
                <p class="break-words text-sm text-muted-foreground">{m.subject ?? "A booking email"}{m.received ? ` · ${m.received}` : ""}</p>
              </div>
              {#if m.candidates.length}
                <ul class="space-y-2" aria-label="It could be">
                  {#each m.candidates as c (c.segment_id)}
                    <li class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border p-3">
                      <div class="min-w-0">
                        <p class="break-words text-sm font-medium">{what(c)}</p>
                        <p class="break-words text-sm text-muted-foreground">{c.trip_name}</p>
                      </div>
                      <Button size="sm" disabled={settling === matchKey(m)} onclick={() => settleMatch(m, c.segment_id)} aria-label={`It’s ${what(c)}`}>It’s this one</Button>
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="text-sm text-muted-foreground">The bookings it could be aren’t yours to see.</p>
              {/if}
              <div class="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={settling === matchKey(m)} onclick={() => settleMatch(m, null)}>It’s a new booking</Button>
                <Button size="sm" variant="ghost" disabled={settling === matchKey(m)} onclick={() => dismissMatch(m)}>Dismiss</Button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if review.who.length}
      <section aria-labelledby="who-title" class="space-y-2">
        <h2 id="who-title" class="eyebrow px-1">Who is this?</h2>
        <p class="px-1 text-sm text-muted-foreground">A booking’s name that Waypoint couldn’t match to anyone in People. Choose who it is, and every booking with that name becomes theirs, and the next one matches by itself.</p>
        <ul class="rows" aria-label="Who is this?">
          {#each review.who as w (w.id)}
            <li class="row items-start" data-testid="who-item">
              <div class="min-w-0 basis-full sm:basis-0 sm:flex-1">
                <p class="break-words font-mono font-medium">{w.name}</p>
                <p class="break-words text-sm text-muted-foreground">{what(w)}</p>
              </div>
              <div class="flex w-full flex-wrap items-center gap-2 sm:w-auto">
                <select bind:value={chosen[w.id]} class={`${selectClass} sm:w-48`} aria-label={`Who is ${w.name}?`}>
                  <option value="">Choose…</option>
                  {#each people as p (p.id)}<option value={String(p.id)}>{p.display_name}</option>{/each}
                  <option value="new">A new guest…</option>
                </select>
                {#if chosen[w.id] === "new"}
                  <Input bind:value={guestName[w.id]} maxlength={100} autocomplete="off" placeholder="Their name" class="sm:w-48" aria-label={`Name for ${w.name}`} />
                {/if}
                <Button size="sm" disabled={!chosen[w.id] || (chosen[w.id] === "new" && !guestName[w.id]?.trim()) || matching === w.id} onclick={() => match(w)}
                  aria-label={`Match ${w.name}`}>{matching === w.id ? "Matching…" : "That’s them"}</Button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  </div>
{/if}

<ConfirmDialog bind:open={asking} title={`Ignore ${ignoring?.sender_domain ?? "this sender"}?`} confirmLabel="Ignore" busyLabel="Ignoring…" destructive
  onconfirm={async () => { const i = ignoring; return i ? await ignore(i) : true; }}>
  {#snippet description()}
    {#if ignoring?.known_sender}<p class="text-signal-ink" data-testid="known-sender-warning">This sender is a travel company Waypoint knows. Ignoring it means its bookings won’t be added.</p>{/if}
    <p>Not travel: Waypoint stops looking at mail from this sender in that mailbox, and {goingCount === 1 ? "this item leaves" : `${goingCount} items from them (this one included) leave`} this list. Bookings already made from their emails stay. Other mailboxes aren’t affected.</p>
    <p>You can undo this in Settings → Mail and AI → Gmail.</p>
  {/snippet}
</ConfirmDialog>

<Sheet bind:open={() => draft !== null, (v) => { if (!v) requestClose(); }} title={draft?.suggested ? (drafts.length > 1 ? "Check these suggestions" : "Check this suggestion") : "Add this booking by hand"} wide onOpenAutoFocus={focusSheet}>
  {#if draft}
    <div class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        {#if !emailOpen}<p class="min-w-0 break-words text-sm font-medium">{subject(draft.item)}</p>{/if}
        <Button type="button" variant="outline" size="sm" class="ml-auto" aria-expanded={emailOpen} aria-controls="review-email" onclick={() => (emailOpen = !emailOpen)}>{emailOpen ? "Hide the email" : "Show the email"}</Button>
      </div>
      <div id="review-email" hidden={!emailOpen}>
        {#if peeks[draft.item.id]}<div data-testid="preview">{@render messagePeek(draft.item)}</div>{/if}
      </div>
      {@render addForm(draft.item)}
    </div>
  {/if}
</Sheet>

<ConfirmDialog bind:open={discarding} title="Discard this booking?" description="What you typed here won’t be saved." confirmLabel="Discard" cancelLabel="Keep editing" destructive
  onconfirm={() => { closeForm(); return true; }} />
