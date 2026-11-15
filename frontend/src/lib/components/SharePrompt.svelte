<script lang="ts">
  import type { Snippet } from "svelte";
  import type { PhotoSharing } from "$lib/api-types";
  import { Button } from "$lib/components/ui/button";
  import { cn } from "$lib/utils";
  import { COULDNT_CHECK, plural, type Scope, type Who } from "$lib/photo-sharing";

  let { who, sharing, scope = $bindable("only_me"), note = "", locked = false, id, heading = "p", eyebrow = "", skipVariant = "outline", class: extra = "", onshare, onskip, actions, foot }: {
    who: Who; sharing: PhotoSharing; scope?: Scope; note?: string; locked?: boolean; id: string; heading?: "p" | "h3"; eyebrow?: string;
    skipVariant?: "outline" | "ghost"; class?: string; onshare: () => unknown; onskip: () => unknown; actions?: Snippet; foot?: Snippet;
  } = $props();

  const title = $derived(sharing.count === null ? COULDNT_CHECK : `${who.mine ? "You have" : `${who.first} has`} ${plural(sharing.count, "photo", "photos")} from this trip`);
  const name = $derived(`prompt-scope-${id}`);
</script>

<div class={cn("space-y-3 rounded-xl bg-surface-2 p-3", extra)} role="group" aria-labelledby={`photo-prompt-${id}`}>
  {#if eyebrow}<p class="eyebrow">{eyebrow}</p>{/if}
  <svelte:element this={heading} id={`photo-prompt-${id}`} class={heading === "h3" ? "text-heading" : "font-medium"}>{title}</svelte:element>
  <p class="text-sm text-muted-foreground">Only {who.subject} see{who.mine ? "" : "s"} this. Nothing from {who.own} library is on the trip until {who.shares} it.</p>
  {#if note}<p class="text-sm text-signal-ink" role="alert">{note}</p>{/if}
  <fieldset class="space-y-2" disabled={locked}>
    <legend class="mb-1 text-sm font-medium">Who can see them</legend>
    <label class="flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm has-[:checked]:border-ring">
      <input type="radio" {name} class="mt-1" checked={scope === "only_me"} onchange={() => (scope = "only_me")} />
      <span><span class="font-medium">{who.only}</span><span class="block text-muted-foreground">They show on this trip for {who.subject} alone. Nobody else on the trip can tell they’re there.</span></span>
    </label>
    <label class="flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm has-[:checked]:border-ring">
      <input type="radio" {name} class="mt-1" checked={scope === "trip"} onchange={() => (scope = "trip")} />
      <span><span class="font-medium">Everyone on this trip</span><span class="block text-muted-foreground">Everyone else on the trip sees them too, in the gallery, on the map and in the trip’s counts.</span></span>
    </label>
  </fieldset>
  <div class="flex flex-wrap gap-2">
    <Button size="sm" disabled={locked || (scope === "trip" && sharing.count === null)} onclick={onshare}>Share on this trip</Button>
    {@render actions?.()}
    <Button variant={skipVariant} size="sm" disabled={locked} onclick={onskip}>Not now</Button>
  </div>
  {@render foot?.()}
</div>
