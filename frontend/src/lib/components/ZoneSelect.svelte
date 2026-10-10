<script lang="ts">
  let { value = $bindable(""), blank, label = undefined, required = false }: { value: string; blank: string; label?: string; required?: boolean } = $props();
  const zones: string[] = (() => { try { return Intl.supportedValuesOf("timeZone"); } catch { return []; } })();
  const kept = $derived(value && !zones.includes(value) ? value : "");
</script>

<select bind:value aria-label={label} {required}
  class="border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm">
  <option value="">{blank}</option>
  {#if kept}<option value={kept}>{kept.replaceAll("_", " ")}</option>{/if}
  {#each zones as zone (zone)}<option value={zone}>{zone.replaceAll("_", " ")}</option>{/each}
</select>
