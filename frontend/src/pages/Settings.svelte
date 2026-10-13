<script lang="ts">
  import { act } from "$lib/act";
  import { api } from "$lib/api";
  import { app, route } from "$lib/app.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import AiSection from "$lib/components/settings/AiSection.svelte";
  import DistanceSection from "$lib/components/settings/DistanceSection.svelte";
  import DataSection from "$lib/components/settings/DataSection.svelte";
  import HomeSection from "$lib/components/settings/HomeSection.svelte";
  import GmailSection from "$lib/components/settings/GmailSection.svelte";
  import LogosSection from "$lib/components/settings/LogosSection.svelte";
  import ImportSection from "$lib/components/settings/ImportSection.svelte";
  import McpSection from "$lib/components/settings/McpSection.svelte";
  import { clearSaved } from "$lib/offline";
  import OfflineSection from "$lib/components/settings/OfflineSection.svelte";
  import RemindersSection from "$lib/components/settings/RemindersSection.svelte";
  import { flightStatus, loadFlightStatus } from "$lib/flightstatus.svelte";
  import { onMount } from "svelte";
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";

  const s = $derived(app.state);
  const user = $derived(s?.user);
  let signingOut = $state(false);
  const flights = $derived(flightStatus.list);
  onMount(loadFlightStatus);

  const GROUPS = [
    { id: "account", label: "Account & household", about: "Who’s signed in, your household and the version.", tasks: ["Sign out", "Household members", "Version and advanced"] },
    { id: "mail", label: "Mail & review", about: "Connect Gmail, reconnect it, choose what is read and set up AI suggestions.", tasks: ["Connect or reconnect Gmail", "Choose labels", "Ignored senders", "AI suggestions"] },
    { id: "travel", label: "Travel preferences", about: "Where home is, miles or kilometres and brand logos.", tasks: ["Home", "Distances", "Brand logos"] },
    { id: "offline", label: "Offline & notifications", about: "Keep your trip on this device, reminders and your calendar.", tasks: ["Offline access", "Reminders", "Calendar subscription"] },
    { id: "assistants", label: "Connected assistants", about: "The AI assistants that can reach Waypoint, and what they may do.", tasks: ["Connect an assistant", "Disconnect an assistant", "Let an assistant read email"] },
    { id: "backup", label: "Backup & import", about: "Download or restore a backup and import past flights.", tasks: ["Download a backup", "Restore a backup", "Import past flights"] },
  ] as const;
  type Group = (typeof GROUPS)[number]["id"];
  const OLD_LINKS: Record<string, Group> = { data: "backup" };
  const landing: Group | "" = new URLSearchParams(location.search).has("gmail") ? "mail" : "";
  const sub = $derived(OLD_LINKS[route.sub] ?? route.sub);
  const group = $derived<(typeof GROUPS)[number] | undefined>(GROUPS.find((g) => g.id === sub) ?? GROUPS.find((g) => g.id === landing));

  const signOut = () => act(async () => {
    await clearSaved();
    const r = await api<{ redirect: string }>("/auth/logout", { method: "POST" });
    location.href = r.redirect;
  }, { busy: (on) => (signingOut = on) });
</script>

<h1 class="mb-4 text-display">{group ? group.label : "Settings"}</h1>

{#if group}
  <nav aria-label="Settings sections" class="mb-6">
    <a href="#settings" class="inline-flex items-center gap-1 rounded-md py-2 text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"><ChevronLeft class="size-4" aria-hidden="true" />All settings</a>
  </nav>
{:else}
  <nav aria-label="Settings sections" class="mb-6">
    <ul class="grid gap-3 md:grid-cols-2">
      {#each GROUPS as g (g.id)}
        <li class="rounded-2xl bg-card p-4 shadow-card">
          <h2 class="font-medium"><a href={`#settings/${g.id}`} class="rounded-md underline-offset-2 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50">{g.label}</a></h2>
          <p class="text-sm text-muted-foreground">{g.about}</p>
          <ul class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm">
            {#each g.tasks as task (task)}<li><a href={`#settings/${g.id}`} class="rounded-md underline underline-offset-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">{task}</a></li>{/each}
          </ul>
        </li>
      {/each}
    </ul>
  </nav>
{/if}

{#if group}
<div class="space-y-8">
  {#if group.id === "account"}
  <section aria-labelledby="account-title" class="space-y-2">
    <h2 id="account-title" class="eyebrow px-1">Account</h2>
    <div class="rows">
      {#if user?.local}
        <div class="row">
          <div><p class="font-medium">Running without sign-in</p><p class="text-sm text-muted-foreground">Waypoint isn’t asking anyone to sign in on this machine.</p></div>
          <Badge variant="outline">Local</Badge>
        </div>
      {:else if user}
        <div class="row">
          <div class="min-w-0">
            <p class="text-sm text-muted-foreground">Signed in as</p>
            <p class="truncate font-medium">{user.name || user.email}</p>
            {#if user.name && user.email}<p class="truncate text-sm text-muted-foreground">{user.email}</p>{/if}
          </div>
          <Button variant="outline" disabled={signingOut} onclick={signOut}>{signingOut ? "Signing out…" : "Sign out"}</Button>
        </div>
      {:else}
        <div class="row"><p class="font-medium">Not signed in</p></div>
      {/if}
    </div>
  </section>

  <section aria-labelledby="household-title" class="space-y-2">
    <h2 id="household-title" class="eyebrow px-1">Household</h2>
    <div class="rows">
      <div class="row">
        <div><p class="font-medium">Household members</p><p class="text-sm text-muted-foreground">Who travels, and their loyalty and Known Traveler numbers.</p></div>
        <Button variant="outline" href="#people">Open People</Button>
      </div>
    </div>
  </section>

  <section aria-labelledby="about-title" class="space-y-2">
    <h2 id="about-title" class="eyebrow px-1">Advanced: for whoever runs Waypoint</h2>
    <dl class="rows">
      <div class="row"><dt class="text-muted-foreground">Version</dt><dd class="code normal-case">{s?.version}</dd></div>
      <div class="row"><dt class="text-muted-foreground">Database</dt><dd class="font-medium">{s?.database === "postgres" ? "Postgres" : "SQLite"}</dd></div>
      {#if flights}
        <div class="row" data-testid="flight-status-usage">
          <dt class="text-muted-foreground">Flight status</dt>
          <dd class="font-medium">{flights.enabled ? `${flights.used} of ${flights.limit} calls used this month` : "Live flight status has not been enabled by your administrator."}</dd>
        </div>
      {/if}
    </dl>
  </section>
  {:else if group.id === "mail"}
    <GmailSection />

    <AiSection />
  {:else if group.id === "travel"}
    <HomeSection />

    <DistanceSection />

    <LogosSection />
  {:else if group.id === "offline"}
    <OfflineSection />

    <RemindersSection />
  {:else if group.id === "assistants"}
    <McpSection />
  {:else}
    <DataSection />

    <ImportSection />
  {/if}
</div>
{/if}
