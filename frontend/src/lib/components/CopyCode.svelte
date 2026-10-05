<script lang="ts">
  import { toast } from "svelte-sonner";

  // A confirmation code you tap to copy (at a counter or a phone call, it's the thing you need).
  let { code, class: klass = "" }: { code: string; class?: string } = $props();

  async function copy() {
    try { await navigator.clipboard.writeText(code); toast.success("Copied"); }
    catch { toast("Couldn’t copy it: select the code instead."); }   // no clipboard (an insecure page, a refused permission)
  }
</script>

<button type="button" class={`code rounded-md underline-offset-2 hover:underline focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none ${klass}`}
  aria-label={`Copy confirmation code ${code}`} onclick={copy}>{code}</button>
