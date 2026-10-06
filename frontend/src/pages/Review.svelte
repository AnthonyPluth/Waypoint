<script lang="ts" module>
  import type { ReviewItem } from "$lib/api-types";

  export const REASONS: Record<ReviewItem["reason"], string> = {
    no_markup: "No booking details found",
    incomplete: "Some details missing",
    broken: "Couldn’t be opened",
  };

  const SECOND_LEVEL = new Set(["co", "com", "org", "net", "ac", "gov"]);

  export function providerFrom(domain: string): string {
    const labels = domain.split(".").filter(Boolean);
    const name = labels.length >= 3 && SECOND_LEVEL.has(labels.at(-2) ?? "") ? labels.at(-3) : labels.at(-2) ?? labels[0] ?? "";
    return (name ?? "").split(/[-_]/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
  }
</script>

<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  import { act, errMsg, ignoreFailure } from "$lib/act";
  import type { Person, Review, ReviewMatch, WhoIsThis } from "$lib/api-types";
  import { refreshState } from "$lib/app.svelte";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Badge } from "$lib/components/ui/badge";
  import { Button, buttonVariants } from "$lib/components/ui/button";
  import { ConfirmDialog } from "$lib/components/ui/confirm-dialog";
  import MessageView from "$lib/components/MessageView.svelte";
  import { Input } from "$lib/components/ui/input";
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

  const KINDS: [string, string][] = [["flight", "Flight"], ["hotel", "Hotel stay"], ["car", "Car rental"], ["train", "Train"]];
  const selectClass = "border-input bg-card dark:bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";

  const sender = (i: ReviewItem) => i.sender_domain || "Unknown sender";
  const subject = (i: ReviewItem) => i.subject || `Mail from ${sender(i).toLowerCase() === "unknown sender" ? "an unknown sender" : sender(i)}${i.received ? ` on ${i.received}` : ""}`;

  type Draft = { item: ReviewItem; suggested: boolean; kind: string; provider: string; confirmation: string; origin: string; destination: string; start: string; end: string; startZone: string; endZone: string; address: string };
  let draft = $state<Draft | null>(null);
  let formError = $state("");
  let saving = $state(false);
  const startAdd = (item: ReviewItem, use = false) => {
    const s = use ? item.suggestion : null;
    draft = s
      ? { item, suggested: true, kind: s.kind, provider: s.provider ?? providerFrom(item.sender_domain), confirmation: s.confirmation ?? "", origin: s.origin,
          destination: s.destination ?? "", start: s.start_local.slice(0, 16), end: s.end_local.slice(0, 16), startZone: s.start_zone ?? "", endZone: s.end_zone ?? "", address: "" }
      : { item, suggested: false, kind: "flight", provider: providerFrom(item.sender_domain), confirmation: "", origin: "", destination: "", start: "", end: "", startZone: "", endZone: "", address: "" };
    formError = "";
    void peek(item);
  };
  type Peek = { state: "loading" } | { state: "ready"; subject: string | null; text: string; html: string | null; truncated: boolean } | { state: "error"; message: string };
  let peeks = $state<Record<number, Peek>>({});
  async function peek(item: ReviewItem) {
    if (peeks[item.id] && peeks[item.id]?.state !== "error") return;
    peeks[item.id] = { state: "loading" };
    try {
      const r = await apiCall<"GET /api/review/{id}/preview">(`/api/review/${item.id}/preview`);
      peeks[item.id] = { state: "ready", subject: r.subject ?? null, text: r.text, html: r.html ?? null, truncated: r.truncated };
    } catch (err) { peeks[item.id] = { state: "error", message: errMsg(err) }; }
  }

  const asking_ai = new SvelteSet<number>();
  const askAi = (item: ReviewItem) => act(async () => {
    await apiCall<"POST /api/review/{id}/suggest">(`/api/review/${item.id}/suggest`, { method: "POST" });
    await settle();
  }, { busy: (on) => (on ? asking_ai.add(item.id) : asking_ai.delete(item.id)) });

  let asking_all = $state(false);
  const unasked = $derived(review?.ai ? review.items.filter((i) => i.mine && !i.suggestion && !asking_ai.has(i.id)) : []);
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

  const placeLabels = (kind: string) => kind === "flight" ? ["From (airport code)", "To (airport code)"] : kind === "hotel" ? ["Hotel", ""] : kind === "car" ? ["Pick-up", "Drop-off"] : kind === "cruise" ? ["Embarkation port", "Disembarkation port"] : ["From (station)", "To (station)"];

  const closeForm = () => {
    if (draft) delete peeks[draft.item.id];
    draft = null;
  };

  async function add(e: SubmitEvent) {
    e.preventDefault();
    const d = draft;
    if (!d) return;
    const flight = d.kind === "flight";
    if (d.kind === "hotel" && !d.startZone.trim() && !d.address.trim()) { formError = "Enter the hotel’s time zone (for example America/New_York), or its address to work it out from"; return; }
    const body = { kind: d.kind as "flight" | "hotel" | "car" | "train" | "cruise", start_local: d.start, end_local: d.end, provider: d.provider, confirmation: d.confirmation, origin: d.origin,
      destination: d.destination, ...(flight ? {} : d.kind === "hotel" ? { start_zone: d.startZone.trim() || null, ...(d.address.trim() && { details: { address: d.address.trim() } }) } : { start_zone: d.startZone, end_zone: d.endZone || d.startZone }) };
    let added = false;
    const ok = await act(async () => {
      const made = await apiCall<"POST /api/segments">("/api/segments", { method: "POST", body });
      added = true;
      await apiCall<"DELETE /api/review/{id}">(`/api/review/${d.item.id}?segment=${made.id}`, { method: "DELETE" });
    }, { busy: (on) => (saving = on), onError: (m) => (formError = added ? `Added, but couldn’t take it off this list: ${m}` : m) });
    if (!ok) { if (added) { closeForm(); await settle(); } return; }
    closeForm();
    toast.success("Added to your trips");
    await settle();
  }

  const dismiss = (i: ReviewItem) => act(async () => {
    await apiCall<"DELETE /api/review/{id}">(`/api/review/${i.id}`, { method: "DELETE" });
    toast.success("Dismissed");
    await settle();
  });

  let ignoring = $state<ReviewItem | null>(null);
  let asking = $state(false);
  const ignore = (i: ReviewItem) => act(async () => {
    await apiCall<"POST /api/review/{id}/ignore">(`/api/review/${i.id}/ignore`, { method: "POST" });
    toast.success(`Ignoring ${i.sender_domain}`);
    await settle();
  });

  let chosen = $state<Record<number, string>>({});
  let guestName = $state<Record<number, string>>({});
  let matching = $state<number | null>(null);
  const what = (w: Pick<WhoIsThis, "kind" | "origin" | "destination" | "start_local" | "provider">) => `${w.kind === "hotel" ? "Stay" : w.kind === "car" ? "Rental" : w.kind === "train" ? "Train" : w.kind === "cruise" ? "Cruise" : "Flight"}${w.origin ? ` ${w.origin}${w.destination ? ` → ${w.destination}` : ""}` : ""} on ${w.start_local.slice(0, 10)}${w.provider ? ` (${w.provider})` : ""}`;

  let settling = $state<string | null>(null);
  const matchKey = (m: ReviewMatch) => `${m.item_id}-${m.index}`;
  const settleMatch = (m: ReviewMatch, segmentId: number | null) => act(async () => {
    await apiCall<"POST /api/review/{id}/match">(`/api/review/${m.item_id}/match`, { method: "POST", body: { index: m.index, segment_id: segmentId } });
    toast.success(segmentId === null ? "Added to your trips" : "Filled in");
    await settle();
  }, { busy: (on) => (settling = on ? matchKey(m) : null) });
  const dismissMatch = (m: ReviewMatch) => act(async () => {
    await apiCall<"DELETE /api/review/{id}">(`/api/review/${m.item_id}`, { method: "DELETE" });
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

<h1 class="mb-6 text-4xl font-bold tracking-tight">Review</h1>

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
        <p class="px-1 text-sm text-muted-foreground">These looked like bookings, and Waypoint couldn’t get one out of them. Only you see the ones from your own mailboxes, unless someone shares theirs (Settings → Mail and AI → Gmail), and then you can add those by hand or dismiss them. Open one in Gmail, or choose Add by hand to read it beside the form. Waypoint keeps each message here, encrypted, so you can read it without Gmail: until the item is dismissed or added, and for as long as a booking you add from it exists.</p>
        {#if unasked.length > 1}
          <div class="px-1"><Button variant="outline" size="sm" disabled={asking_all} onclick={() => askAll(unasked)}>{asking_all ? "Asking…" : `Ask AI about all ${unasked.length}`}</Button></div>
        {/if}
        <ul class="rows" aria-label="Couldn’t read">
          {#each review.items as item (item.id)}
            <li class="row items-start" data-testid="review-item">
              <div class="min-w-0 basis-full">
                <p class="break-words font-medium">{subject(item)}</p>
                <p class="break-words text-sm text-muted-foreground">{[item.received && `Sent ${item.received}`, item.mine ? `to ${item.address}` : `in ${item.owner}’s mailbox, shared with the household`].filter(Boolean).join(" · ")}</p>
                <p class="mt-1"><Badge variant="secondary">{REASONS[item.reason]}</Badge>{#if item.suggestion} <Badge variant="outline">AI suggestion</Badge>{/if}</p>
                {#if item.suggestion_error}<p class="mt-1 text-sm text-muted-foreground" role="status">{item.suggestion_error}</p>{/if}
              </div>
              <div class="flex basis-full flex-wrap gap-2">
                {#if item.gmail_url}<a class={buttonVariants({ variant: "outline", size: "sm" })} href={item.gmail_url} target="_blank" rel="noopener noreferrer" aria-label={`Open “${subject(item)}” in Gmail`}>Open in Gmail</a>{/if}
                {#if review.ai && item.mine}<Button variant="outline" size="sm" disabled={asking_all || asking_ai.has(item.id)} onclick={() => askAi(item)} aria-label={`Ask AI about “${subject(item)}”`}>{asking_ai.has(item.id) ? "Asking…" : item.suggestion ? "Ask again" : "Ask AI"}</Button>{/if}
                {#if item.suggestion}<Button size="sm" onclick={() => startAdd(item, true)} aria-label={`Check the AI’s suggestion for “${subject(item)}”`}>Check suggestion</Button>{/if}
                <Button variant="outline" size="sm" onclick={() => startAdd(item)} aria-label={`Add “${subject(item)}” by hand`}>Add by hand</Button>
                {#if item.sender_domain && item.mine}<Button variant="outline" size="sm" onclick={() => { ignoring = item; asking = true; }} aria-label={`Ignore ${item.sender_domain}`}>Ignore this sender</Button>{/if}
                <Button variant="outline" size="sm" onclick={() => dismiss(item)} aria-label={`Dismiss “${subject(item)}”`}>Dismiss</Button>
              </div>
            </li>
            {#if peeks[item.id] && draft?.item.id === item.id}
              {@const p = peeks[item.id]}
              <li class="row items-stretch" data-testid="preview">
                <div class="w-full min-w-0 space-y-2" aria-label={`The message from ${sender(item)}`} role="region">
                  {#if p.state === "loading"}<p class="text-sm text-muted-foreground" role="status">Fetching the message from Gmail…</p>
                  {:else if p.state === "error"}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{p.message}</p>
                  {:else}
                    <MessageView subject={p.subject} text={p.text} html={p.html} truncated={p.truncated} />
                  {/if}
                </div>
              </li>
            {/if}
            {#if draft && draft.item.id === item.id}
              {@const d = draft}
              {@const labels = placeLabels(d.kind)}
              <li class="row items-stretch">
                <form class="flex w-full flex-col gap-4" data-editor onsubmit={add} aria-labelledby={`add-${item.id}`}>
                  <h3 id={`add-${item.id}`} class="font-medium">{d.suggested ? "Check this suggestion" : "Add this booking by hand"}</h3>
                  {#if d.suggested}<p class="text-sm text-muted-foreground">An AI read the email and suggested this. It can be wrong: check each field against the booking, change what’s off, then add it.</p>{/if}
                  {#if item.received}<p class="text-sm text-muted-foreground">The email was sent {item.received}. Enter the times as they read on the booking, at the place they happen.</p>{/if}
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">What is it?</span>
                    <select bind:value={d.kind} class={selectClass}>{#each KINDS as [key, name] (key)}<option value={key}>{name}</option>{/each}</select></label>
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Provider</span>
                    <Input bind:value={d.provider} maxlength={100} autocomplete="off" /></label>
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Confirmation code</span>
                    <Input bind:value={d.confirmation} maxlength={50} autocomplete="off" spellcheck={false} /></label>
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{labels[0]}</span>
                    <Input bind:value={d.origin} required maxlength={100} autocomplete="off" /></label>
                  {#if labels[1]}
                    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{labels[1]}</span>
                      <Input bind:value={d.destination} required={d.kind === "flight"} maxlength={100} autocomplete="off" /></label>
                  {/if}
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{d.kind === "hotel" ? "Check-in" : d.kind === "car" ? "Pick-up time" : "Departs"}</span>
                    <Input type="datetime-local" bind:value={d.start} required /></label>
                  <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">{d.kind === "hotel" ? "Check-out" : d.kind === "car" ? "Drop-off time" : "Arrives"}</span>
                    <Input type="datetime-local" bind:value={d.end} required /></label>
                  {#if d.kind === "hotel"}
                    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Address</span>
                      <Input bind:value={d.address} maxlength={300} autocomplete="off" />
                      <span class="text-muted-foreground">Waypoint works the time zone out from it when you leave the time zone empty.</span></label>
                    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone</span>
                      <Input bind:value={d.startZone} maxlength={64} autocomplete="off" spellcheck={false} placeholder="America/New_York" />
                      <span class="text-muted-foreground">Check-in and check-out are both at the hotel. Leave this empty to work it out from the address above.</span></label>
                  {:else if d.kind !== "flight"}
                    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone where it starts</span>
                      <Input bind:value={d.startZone} required maxlength={64} autocomplete="off" spellcheck={false} placeholder="America/New_York" /></label>
                    <label class="flex flex-col gap-1.5 text-sm"><span class="font-medium">Time zone where it ends</span>
                      <Input bind:value={d.endZone} maxlength={64} autocomplete="off" spellcheck={false} placeholder="Same as where it starts" /></label>
                  {:else}
                    <p class="text-sm text-muted-foreground">A flight’s time zones come from its airports.</p>
                  {/if}
                  {#if formError}<p class="rounded-lg bg-signal-soft p-3 text-sm text-signal-ink" role="alert">{formError}</p>{/if}
                  <div class="flex flex-wrap gap-2">
                    <Button type="submit" disabled={saving}>{saving ? "Adding…" : "Add to my trips"}</Button>
                    <Button type="button" variant="outline" disabled={saving} onclick={closeForm}>Cancel</Button>
                  </div>
                </form>
              </li>
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
  description="Waypoint stops looking at mail from this sender in that mailbox, and their other items leave this list. Other mailboxes aren’t affected."
  onconfirm={async () => { const i = ignoring; return i ? await ignore(i) : true; }} />
