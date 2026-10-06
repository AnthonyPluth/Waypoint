<script lang="ts">
  import { toast } from "svelte-sonner";

  let { code, class: klass = "", label = "confirmation code", multiline = false }: { code: string; class?: string; label?: string; multiline?: boolean } = $props();

  async function copy() {
    try { await navigator.clipboard.writeText(code); toast.success("Copied"); }
    catch { toast("Couldn’t copy it: select the code instead."); }
  }
</script>

<button type="button" class={`${multiline ? "whitespace-pre-line break-words text-left" : "code"} rounded-md underline-offset-2 hover:underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none ${klass}`}
  aria-label={`Copy ${label} ${code}`} onclick={copy}>{code}</button>
