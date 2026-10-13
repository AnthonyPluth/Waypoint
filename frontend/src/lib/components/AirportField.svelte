<script lang="ts">
  import { searchAirports } from "$lib/airport-zones";
  import type { Airport } from "$lib/api-types";
  import { Input } from "$lib/components/ui/input";

  let { value = $bindable(""), placeholder, field, invalid = false, describedby = undefined }: { value: string; placeholder: string; field: string; invalid?: boolean; describedby?: string } = $props();
  const uid = $props.id();
  const listId = `airports-${uid}`;
  let options = $state<Airport[]>([]);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latest = 0;

  function search(text: string) {
    clearTimeout(timer);
    const mine = ++latest;
    timer = setTimeout(async () => {
      const found = await searchAirports(text);
      if (mine === latest) options = found;
    }, 150);
  }

  const describe = (a: Airport) => [a.name, a.city, a.country].filter(Boolean).join(", ");
</script>

<span data-field={field} class="contents">
  <Input bind:value maxlength={60} list={listId} autocomplete="off" spellcheck={false} {placeholder} aria-invalid={invalid ? "true" : undefined} aria-describedby={describedby}
    oninput={(e) => search(e.currentTarget.value)} />
  <datalist id={listId}>
    {#each options as a (a.code)}<option value={a.code} label={describe(a)}></option>{/each}
  </datalist>
</span>
