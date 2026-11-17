<script lang="ts">
  import Copy from "@lucide/svelte/icons/copy";
  import { toast } from "svelte-sonner";

  let { text, name }: { text: string; name: string } = $props();

  async function copy() {
    try { await navigator.clipboard.writeText(text); toast.success("Copied"); }
    catch { toast("Couldn’t copy it: select the text instead."); }
  }
</script>

<button type="button" class="inline-flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-[10px] border border-input bg-secondary px-2.5 text-[13px] font-semibold hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none phone:min-h-11" aria-label={name} onclick={copy}><Copy class="size-3.5" aria-hidden="true" /> Copy</button>
