<script lang="ts">
  import { errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Stats } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { loadCountries, type Country } from "$lib/map";
  import { cardSvg, firstName, mapSvg, outlinesFor, reviewFacts, shareOrDownload, svgToPng } from "$lib/review";
  import { count } from "$lib/stats";

  // A person's year as a few full-screen cards, then a summary card to share. The picture is made here, on the device, and goes
  // to the share sheet (or is downloaded): nothing is uploaded. The first name is on it only when "Show the first name" is ticked.
  let { stats, person, name = null, onclose }: { stats: Stats; person: number | "all"; name?: string | null; onclose: () => void } = $props();

  let allTime = $state<Stats | null>(null);   // to tell which countries were new; without it no country is called new
  let countries = $state<Country[] | null>(null);
  let step = $state(0);
  let showName = $state(false);
  let outlinesFailed = $state(false);
  let busy = $state(false);
  let result = $state("");
  let problem = $state("");

  $effect(() => {
    apiCall<"GET /api/stats">(`/api/stats?person=${person}&year=all`).then((s) => { allTime = s; }).catch(() => { allTime = null; });   // (the new-countries card is left out)
    loadCountries().then((c) => { countries = c; }).catch(() => { countries = []; outlinesFailed = true; });   // (the map is drawn without outlines, and says so)
  });

  const facts = $derived(reviewFacts(stats, allTime));
  const outlines = $derived(countries ? outlinesFor(countries, stats) : []);
  const mine = $derived(person === "all" ? null : firstName(name));
  const cardName = $derived(showName ? mine : null);
  const card = $derived(cardSvg(facts, outlines, cardName));
  const dataUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

  type Card = { id: string; eyebrow: string; big?: string; lines: string[] };
  const cards = $derived<Card[]>([
    { id: "distance", eyebrow: "You travelled", big: facts.distance, lines: facts.comparisons },
    { id: "flights", eyebrow: "In the air", big: `${count(facts.flights)} ${facts.flights === 1 ? "flight" : "flights"}`, lines: [`${facts.airTime} in the air`] },
    ...(facts.countries.length ? [{ id: "countries", eyebrow: "Countries", big: `${facts.countries.length} ${facts.countries.length === 1 ? "country" : "countries"}`,
      lines: [...(facts.newCountries.length ? [`${facts.newCountries.length} new this year: ${facts.newCountries.join(", ")}`] : []), facts.countries.join(", ")] }] : []),
    ...(facts.topRoute ? [{ id: "route", eyebrow: "Top route", big: `${facts.topRoute.a} – ${facts.topRoute.b}`,
      lines: [`${count(facts.topRoute.flights)} ${facts.topRoute.flights === 1 ? "flight" : "flights"}`, ...(facts.topAirport ? [`Most-visited airport: ${facts.topAirport}`] : [])] }] : []),
    ...(facts.nights ? [{ id: "nights", eyebrow: "Away from home", big: `${count(facts.nights)} ${facts.nights === 1 ? "night" : "nights"}`, lines: ["in hotels and rentals"] }] : []),
    ...(facts.cruises.count ? [{ id: "cruises", eyebrow: "At sea", big: `${count(facts.cruises.count)} ${facts.cruises.count === 1 ? "cruise" : "cruises"}`,
      lines: [`${count(facts.cruises.nights)} ${facts.cruises.nights === 1 ? "night" : "nights"} aboard`, `${count(facts.cruises.seaDays)} ${facts.cruises.seaDays === 1 ? "sea day" : "sea days"}`] }] : []),
    { id: "map", eyebrow: "Where you went", lines: [] },
    { id: "share", eyebrow: "Share", lines: [] },
  ]);
  const current = $derived(cards[Math.min(step, cards.length - 1)]);
  const last = $derived(step >= cards.length - 1);

  async function share() {
    busy = true; result = ""; problem = "";
    try {
      const out = await shareOrDownload(await svgToPng(card), `waypoint-${facts.year}.png`, `My ${facts.year} in travel`);
      result = out === "shared" ? "Shared." : out === "downloaded" ? "Saved the picture to your downloads." : "";
    } catch (err) { problem = errMsg(err); } finally { busy = false; }
  }
</script>

<svelte:window onkeydown={(e) => { if (e.key === "Escape") onclose(); else if (e.key === "ArrowRight" && !last) step++; else if (e.key === "ArrowLeft" && step > 0) step--; }} />

<div class="fixed inset-0 z-50 flex flex-col bg-background" role="dialog" aria-modal="true" aria-label="{facts.year} in review" data-testid="year-in-review">
  <div class="flex items-center justify-between gap-3 px-4 py-3">
    <ol class="flex gap-1.5" aria-label="Card {step + 1} of {cards.length}">
      {#each cards as c, i (c.id)}<li class="h-1.5 w-6 rounded-full {i <= step ? 'bg-primary' : 'bg-muted'}"></li>{/each}
    </ol>
    <Button variant="ghost" size="sm" onclick={onclose}>Close</Button>
  </div>

  <div class="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-4 overflow-y-auto px-6 py-4">
    <p class="eyebrow">{current.eyebrow} · {facts.year}</p>
    {#if current.id === "map"}
      {#if countries === null}
        <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading the map"></div>
      {:else}
        <img src={dataUrl(mapSvg(facts, outlines))} alt="Map of the airports and routes flown in {facts.year}" class="w-full rounded-2xl" />
      {#if outlinesFailed}<p class="text-sm text-muted-foreground" role="status">The country outlines couldn’t load, so the map shows only your airports and routes.</p>{/if}
      {/if}
    {:else if current.id === "share"}
      {#if countries === null}
        <div class="aspect-[4/5] animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Making the picture"></div>
      {:else}
        <img src={dataUrl(card)} alt="The picture to share: {facts.year}, {facts.distance}, {facts.flights} flights" class="mx-auto w-full max-w-sm rounded-2xl" data-testid="share-card" />
      {#if outlinesFailed}<p class="text-sm text-muted-foreground" role="status">The country outlines couldn’t load, so the map shows only your airports and routes.</p>{/if}
      {/if}
      {#if mine}
        <label class="flex items-center gap-2 text-sm font-medium"><input type="checkbox" bind:checked={showName} class="size-4 accent-primary" /> Show the first name ({mine})</label>
      {/if}
      <p class="text-sm text-muted-foreground">Made on this device. It shows totals, the top route, countries and the map: no dates, confirmation codes, loyalty numbers or hotels.</p>
      <div class="flex flex-wrap items-center gap-3">
        <Button onclick={share} disabled={busy || countries === null}>{busy ? "Making the picture…" : "Share"}</Button>
        {#if result}<span class="text-sm text-muted-foreground" role="status">{result}</span>{/if}
      </div>
      {#if problem}<Alert role="alert"><AlertDescription>Couldn’t make the picture: {problem}</AlertDescription></Alert>{/if}
    {:else}
      {#if current.big}<p class="text-5xl font-semibold tracking-tight sm:text-6xl">{current.big}</p>{/if}
      {#each current.lines as line (line)}<p class="text-lg text-muted-foreground">{line}</p>{/each}
    {/if}
  </div>

  <div class="flex justify-between gap-3 px-4 py-4">
    <Button variant="outline" disabled={step === 0} onclick={() => step--}>Back</Button>
    <Button disabled={last} onclick={() => step++}>Next</Button>
  </div>
</div>
