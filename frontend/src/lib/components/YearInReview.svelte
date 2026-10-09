<script lang="ts">
  import { errMsg } from "$lib/act";
  import { apiCall } from "$lib/contract";
  import type { Stats } from "$lib/api-types";
  import { Alert, AlertDescription } from "$lib/components/ui/alert";
  import { Button } from "$lib/components/ui/button";
  import { loadCountries, type Country } from "$lib/map";
  import { cardSvg, imageInputs, mapSvg, outlinesFor, reviewFacts, saveImage, svgToPng } from "$lib/review";
  import { count } from "$lib/stats";

  let { stats, person, onclose }: { stats: Stats; person: number | "all"; onclose: () => void } = $props();

  let allTime = $state<Stats | null>(null);
  let countries = $state<Country[] | null>(null);
  let step = $state(0);
  let outlinesFailed = $state(false);
  let busy = $state(false);
  let result = $state("");
  let problem = $state("");

  $effect(() => {
    apiCall<"GET /api/stats">(`/api/stats?person=${person}&year=all`).then((s) => { allTime = s; }).catch(() => { allTime = null; });
    loadCountries().then((c) => { countries = c; }).catch(() => { countries = []; outlinesFailed = true; });
  });

  const facts = $derived(reviewFacts(stats, allTime));
  const outlines = $derived(countries ? outlinesFor(countries, stats) : []);
  const inputs = $derived(imageInputs(facts));
  const card = $derived(cardSvg(inputs, outlines));
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
    { id: "save", eyebrow: "Save as image", lines: [] },
  ]);
  const current = $derived(cards[Math.min(step, cards.length - 1)]);
  const last = $derived(step >= cards.length - 1);

  async function save() {
    busy = true; result = ""; problem = "";
    try {
      saveImage(await svgToPng(card), `waypoint-${facts.year}.png`);
      result = "Saved the image to your downloads.";
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

  <div class="mx-auto flex w-full {current.id === "save" ? "max-w-3xl" : "max-w-xl"} flex-1 flex-col gap-4 overflow-y-auto px-6 py-4 [&>:first-child]:mt-auto [&>:last-child]:mb-auto">
    <p class="eyebrow text-signal-ink">{current.eyebrow} · {facts.year}</p>
    {#if current.id === "map"}
      {#if countries === null}
        <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Loading the map"></div>
      {:else}
        <img src={dataUrl(mapSvg(facts, outlines))} alt="Map of the airports and routes flown in {facts.year}" class="w-full rounded-2xl border border-border" />
      {#if outlinesFailed}<p class="text-sm text-muted-foreground" role="status">The country outlines couldn’t load, so the map shows only your airports and routes.</p>{/if}
      {/if}
    {:else if current.id === "save"}
      <div class="grid gap-5 md:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] md:items-start">
        <div class="space-y-2">
          {#if countries === null}
            <div class="mx-auto aspect-[4/5] w-full max-w-sm animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" aria-busy="true" aria-label="Making the image"></div>
          {:else}
            <img src={dataUrl(card)} alt="The image to save: {facts.year}, {facts.distance}, {facts.flights} flights" class="mx-auto w-full max-w-sm rounded-2xl border border-border" data-testid="save-card" />
            {#if outlinesFailed}<p class="text-sm text-muted-foreground" role="status">The country outlines couldn’t load, so the map shows only your airports and routes.</p>{/if}
          {/if}
        </div>
        <div class="space-y-4">
          <div class="flex flex-wrap items-center gap-3">
            <Button onclick={save} disabled={busy || countries === null}>{busy ? "Making the image…" : "Save as image"}</Button>
            {#if result}<span class="text-sm text-muted-foreground" role="status">{result}</span>{/if}
          </div>
          {#if problem}<Alert role="alert"><AlertDescription>Couldn’t make the image: {problem}</AlertDescription></Alert>{/if}
        </div>
      </div>
    {:else}
      {#if current.big}<p class="text-5xl font-semibold tracking-tight tabular-nums text-foreground sm:text-6xl">{current.big}</p>{/if}
      {#each current.lines as line (line)}<p class="text-lg text-muted-foreground">{line}</p>{/each}
    {/if}
  </div>

  <div class="flex justify-between gap-3 px-4 py-4">
    <Button variant="outline" disabled={step === 0} onclick={() => step--}>Back</Button>
    <Button disabled={last} onclick={() => step++}>Next</Button>
  </div>
</div>
