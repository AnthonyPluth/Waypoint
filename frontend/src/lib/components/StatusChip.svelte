<script lang="ts">
  import type { Chip, Tone } from "$lib/status";

  let { chip, small = false, class: cls = "" }: { chip: Chip; small?: boolean; class?: string } = $props();

  const TONE: Record<Tone, string> = {
    ok: "bg-status-ok-soft text-status-ok-ink",
    warn: "bg-status-warn-soft text-status-warn-ink",
    bad: "bg-status-bad-soft text-status-bad-ink",
    info: "bg-status-info-soft text-status-info-ink",
    quiet: "bg-status-quiet-soft text-status-quiet-ink",
  };
</script>

{#key chip.label}<span class={`status-chip inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full font-semibold ${small ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-0.5 text-xs"} ${TONE[chip.tone]} ${cls}`} data-tone={chip.tone}>
  <span class="size-1.5 rounded-full bg-current" aria-hidden="true"></span>{chip.label}
</span>{/key}
