<script lang="ts">
  import { Combobox } from "bits-ui";
  import { tick } from "svelte";
  import { MAX_SHOWN, buildIndex, describeZone, searchZones, supportedZones, zoneEntry, zoneLabel } from "$lib/zone-search";

  let { value = $bindable(""), blank, label = undefined, required = false, invalid = false, describedby = undefined }: { value: string; blank: string; label?: string; required?: boolean; invalid?: boolean; describedby?: string } = $props();

  const FIELD = "border-input bg-secondary w-full rounded-xl border px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] md:text-sm";
  const uid = $props.id();
  const listId = `zone-list-${uid}`;
  const CLEAR = "waypoint:clear";
  const zones = supportedZones();
  const index = zones ? buildIndex(zones) : [];
  const resting = $derived(value ? zoneLabel(value) : "");
  let text = $state("");
  let editing = $state(false);
  let open = $state(false);
  let box: HTMLInputElement | null = $state(null);

  const entries = $derived(value && !index.some((entry) => entry.zone === value) ? [zoneEntry(value), ...index] : index);
  const matches = $derived(searchZones(entries, editing ? text : "", MAX_SHOWN));
  const showBlank = $derived(!editing || !text.trim());

  $effect(() => {
    if (!editing && text !== resting) text = resting;
  });

  function settle() {
    editing = false;
    text = resting;
  }

  async function pick(next: string) {
    value = next === CLEAR ? "" : next;
    editing = false;
    open = false;
    await tick();
    text = resting;
  }

  function typed(event: Event) {
    editing = true;
    text = (event.currentTarget as HTMLInputElement).value;
    open = true;
  }

  function keydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      settle();
      return;
    }
    if (event.key === "Tab" && open) {
      const active = box?.getAttribute("aria-activedescendant");
      const chosen = active ? document.getElementById(active)?.dataset.value : undefined;
      if (chosen) pick(chosen);
    }
  }

  function changed(next: boolean) {
    open = next;
    if (!next) settle();
  }
</script>

{#if zones}
  <Combobox.Root type="single" allowDeselect={false} bind:open {value} onValueChange={pick} onOpenChange={changed}>
    <Combobox.Input bind:ref={box} class={FIELD} oninput={typed} onkeydown={keydown} onfocus={() => (open = true)} onclick={() => (open = true)}>
      {#snippet child({ props })}
        <input {...props} value={text} aria-label={label} aria-controls={open ? listId : undefined} aria-invalid={invalid ? "true" : undefined} aria-describedby={describedby} placeholder={blank} {required} autocomplete="off" autocapitalize="off" spellcheck={false} />
      {/snippet}
    </Combobox.Input>
    <Combobox.Content id={listId} sideOffset={4} collisionPadding={8} class="zone-list" onpointerdown={(event) => event.preventDefault()}>
      <Combobox.Viewport class="zone-viewport">
        {#if showBlank}
          <Combobox.Item value={CLEAR} label={blank} class="zone-option">
            {#if value}<span class="font-medium">Clear</span><span class="text-muted-foreground">{blank}</span>{:else}<span>{blank}</span>{/if}
          </Combobox.Item>
        {/if}
        {#each matches as entry (entry.zone)}
          <Combobox.Item value={entry.zone} label={entry.label} aria-label={describeZone(entry)} class="zone-option">
            <span>{entry.label}</span>
            {#if entry.generic}<span class="text-muted-foreground">{entry.generic}</span>{/if}
          </Combobox.Item>
        {:else}
          {#if !showBlank}<Combobox.Item value="waypoint:none" label="No matching time zone" disabled class="zone-empty">No matching time zone</Combobox.Item>{/if}
        {/each}
      </Combobox.Viewport>
    </Combobox.Content>
  </Combobox.Root>
{:else}
  <input bind:value aria-label={label} aria-invalid={invalid ? "true" : undefined} aria-describedby={describedby} {required} placeholder={blank} autocomplete="off" autocapitalize="off" spellcheck={false} class={FIELD} />
{/if}
