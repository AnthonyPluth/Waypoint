<script lang="ts">
  import type { Trip } from "$lib/api-types";
  import { countdown, nightsWords, stripLabel, stubWords, tripPeople } from "$lib/trips";
  import AvatarStack from "./AvatarStack.svelte";
  import TripKinds from "./TripKinds.svelte";

  type Props = { trip: Trip; today: string; form: "card" | "hero" | "row"; featured?: boolean; current?: boolean; onclick?: (e: MouseEvent) => void };
  let { trip, today, form, featured = false, current = false, onclick }: Props = $props();

  const stub = $derived(stubWords(trip, today));
  const pill = $derived(countdown(trip, today));
  const nights = $derived(nightsWords(trip));
  const people = $derived(tripPeople(trip));
  const place = $derived([trip.destination, nights].filter(Boolean).join(" · "));
  const rowLine = $derived([nights, pill.toLowerCase()].filter(Boolean).join(" · "));
  const border = $derived(current ? "border-primary bg-surface-2" : featured ? "border-primary/35" : "border-border");
  const monthTone = $derived(featured ? "text-primary" : "text-signal");
  const pillTone = $derived(featured ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground");
  const link = "block h-full overflow-hidden rounded-2xl border bg-card shadow-card transition-colors hover:bg-surface-3 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none";
</script>

<a class={`${link} ${border}`} href={`#trip/${trip.id}`} aria-current={current ? "true" : undefined} {onclick}>
  {#if form === "card"}
    <span class="flex h-full">
      <span class={`flex w-[92px] shrink-0 flex-col items-center justify-center gap-0.5 border-r-2 border-dashed border-border px-2 py-4 text-center ${featured ? "bg-primary/8" : ""}`} data-testid="stub">
        {#if stub.month}
          <span class={`text-sm font-semibold tracking-wider [font-variant-caps:all-small-caps] ${monthTone}`}>{stub.month}</span>
          <span class="text-3xl leading-none font-bold">{stub.day}</span>
          {#if stub.note}<span class="text-xs text-muted-foreground">{stub.note}</span>{/if}
        {:else}
          <span class="text-sm text-muted-foreground">{stub.note}</span>
        {/if}
      </span>
      <span class="flex min-w-0 flex-1 flex-col gap-1.5 p-4">
        <span class="flex items-start justify-between gap-3">
          <span class="min-w-0 break-words text-lg font-bold tracking-tight">{trip.name}</span>
          {#if pill}<span class={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${pillTone}`} data-testid="pill">{pill}</span>{/if}
        </span>
        {#if place}<span class="block text-sm text-muted-foreground">{place}</span>{/if}
        <span class="mt-auto flex items-center justify-between gap-3 pt-2">
          <TripKinds trip={trip} />
          <AvatarStack {people} />
        </span>
      </span>
    </span>
  {:else if form === "hero"}
    <span class={`flex items-center justify-between gap-3 border-b-2 border-dashed border-border px-4 py-2.5 ${featured ? "bg-primary/8" : ""}`} data-testid="stub">
      <span class={`mono text-sm font-semibold ${monthTone}`}>{stripLabel(trip, today)}</span>
      {#if pill}<span class={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${pillTone}`} data-testid="pill">{pill}</span>{/if}
    </span>
    <span class="flex flex-col gap-1.5 p-4">
      <span class="break-words text-lg font-bold tracking-tight">{trip.name}</span>
      {#if place}<span class="block text-sm text-muted-foreground">{place}</span>{/if}
      <span class="flex items-center justify-between gap-3 pt-2">
        <TripKinds trip={trip} />
        <AvatarStack {people} />
      </span>
    </span>
  {:else}
    <span class="flex items-center gap-3 p-3">
      <span class="flex h-[54px] w-12 shrink-0 flex-col items-center justify-center rounded-xl bg-surface-3 text-center" data-testid="stub">
        {#if stub.month}
          <span class="text-xs font-semibold tracking-wider text-signal [font-variant-caps:all-small-caps]">{stub.month}</span>
          <span class="text-lg leading-none font-bold">{stub.day}</span>
        {:else}
          <span class="text-[11px] leading-tight text-muted-foreground">{stub.note}</span>
        {/if}
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate font-bold tracking-tight">{trip.name}</span>
        {#if rowLine}<span class="block truncate text-sm text-muted-foreground">{rowLine}</span>{/if}
      </span>
      <AvatarStack {people} />
    </span>
  {/if}
</a>
