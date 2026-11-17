<script lang="ts">
  import GitMerge from "@lucide/svelte/icons/git-merge";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import { OptionsMenu } from "./index";

  let { onmerge, ondelete }: { onmerge: () => void; ondelete: () => void } = $props();
</script>

<OptionsMenu popup iconOnly variant="ghost" label="Trip options" text="Trip options" items={[
  { label: "Merge another trip", icon: GitMerge, onselect: onmerge },
  { label: "Delete trip", icon: Trash2, destructive: true, divided: true, onselect: ondelete },
]} />
