<script lang="ts">
  import { Combobox } from "bits-ui";
  import { searchAirports } from "$lib/airport-zones";
  import type { Airport } from "$lib/api-types";

  let { value = $bindable(""), placeholder, field, invalid = false, describedby = undefined }: { value: string; placeholder: string; field: string; invalid?: boolean; describedby?: string } = $props();

  const FIELD = "border-input bg-secondary placeholder:text-muted-foreground flex h-10 w-full min-w-0 rounded-xl border px-3 py-1 text-base outline-none transition-[color,box-shadow] md:text-sm focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/40 aria-invalid:border-destructive";
  const uid = $props.id();
  const listId = `airports-${uid}`;
  let options = $state<Airport[]>([]);
  let open = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latest = 0;

  function search(text: string) {
    clearTimeout(timer);
    const mine = ++latest;
    timer = setTimeout(async () => {
      const found = await searchAirports(text);
      if (mine !== latest) return;
      options = found ?? [];
      open = options.length > 0;
    }, 150);
  }

  function typed(event: Event) {
    value = (event.currentTarget as HTMLInputElement).value;
    search(value);
  }

  function pick(code: string) {
    clearTimeout(timer);
    latest++;
    if (code) value = code;
    options = [];
    open = false;
  }

  const where = (a: Airport) => [a.city, a.country].filter(Boolean).join(", ");
  const describe = (a: Airport) => [a.code, a.name, where(a)].filter(Boolean).join(", ");
</script>

<span data-field={field} class="contents">
  <Combobox.Root type="single" allowDeselect={false} bind:open value="" onValueChange={pick} onOpenChange={(next) => { open = next && options.length > 0; }}>
    <Combobox.Input oninput={typed}>
      {#snippet child({ props })}
        <input {...props} {value} class={FIELD} maxlength={60} {placeholder} autocomplete="off" autocapitalize="off" spellcheck={false} aria-controls={open ? listId : undefined} aria-invalid={invalid ? "true" : undefined} aria-describedby={describedby} />
      {/snippet}
    </Combobox.Input>
    <Combobox.Content id={listId} sideOffset={4} collisionPadding={8} class="zone-list" onpointerdown={(event) => event.preventDefault()}>
      <Combobox.Viewport class="zone-viewport">
        {#each options as a (a.code)}
          <Combobox.Item value={a.code} label={a.code} aria-label={describe(a)} class="zone-option airport-option">
            <span class="font-mono font-semibold">{a.code}</span>
            <span class="airport-name">{a.name}</span>
            <span class="text-muted-foreground airport-where">{where(a)}</span>
          </Combobox.Item>
        {/each}
      </Combobox.Viewport>
    </Combobox.Content>
  </Combobox.Root>
</span>
