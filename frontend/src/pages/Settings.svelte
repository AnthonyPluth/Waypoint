<script lang="ts">
  import { act } from "$lib/act";
  import { api } from "$lib/api";
  import { app, route } from "$lib/app.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import AiSection from "$lib/components/settings/AiSection.svelte";
  import DistanceSection from "$lib/components/settings/DistanceSection.svelte";
  import DataSection from "$lib/components/settings/DataSection.svelte";
  import GmailSection from "$lib/components/settings/GmailSection.svelte";
  import LogosSection from "$lib/components/settings/LogosSection.svelte";
  import ImportSection from "$lib/components/settings/ImportSection.svelte";
  import McpSection from "$lib/components/settings/McpSection.svelte";
  import RemindersSection from "$lib/components/settings/RemindersSection.svelte";
  import { flightStatus, loadFlightStatus } from "$lib/flightstatus.svelte";
  import { onMount } from "svelte";
  import { cn } from "$lib/utils";

  const s = $derived(app.state);
  const user = $derived(s?.user);
  let signingOut = $state(false);
  const flights = $derived(flightStatus.list);
  onMount(loadFlightStatus);

  const TABS = [["account", "Account"], ["mail", "Mail and AI"], ["travel", "Travel"], ["data", "Data"]] as const;
  type Tab = (typeof TABS)[number][0];
  const landing: Tab | "" = new URLSearchParams(location.search).has("gmail") ? "mail" : "";
  const tab = $derived<Tab>((TABS.find(([id]) => id === route.sub)?.[0]) ?? (landing || "account"));

  const signOut = () => act(async () => {
    const r = await api<{ redirect: string }>("/auth/logout", { method: "POST" });
    location.href = r.redirect;
  }, { busy: (on) => (signingOut = on) });
</script>

<h1 class="mb-4 text-display">Settings</h1>

<nav aria-label="Settings sections" class="-mx-4 mb-6 overflow-x-auto px-4 md:mx-0 md:px-0">
  <ul class="flex w-max gap-1 rounded-2xl bg-muted p-1 md:w-fit">
    {#each TABS as [id, label] (id)}
      <li>
        <a href={`#settings/${id}`} aria-current={tab === id ? "page" : undefined}
          class={cn("block rounded-xl px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            tab === id ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground")}>{label}</a>
      </li>
    {/each}
  </ul>
</nav>

<div class="space-y-8">
  {#if tab === "account"}
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

  <section aria-labelledby="about-title" class="space-y-2">
    <h2 id="about-title" class="eyebrow px-1">About</h2>
    <dl class="rows">
      <div class="row"><dt class="text-muted-foreground">Version</dt><dd class="code normal-case">{s?.version}</dd></div>
      <div class="row"><dt class="text-muted-foreground">Database</dt><dd class="font-medium">{s?.database === "postgres" ? "Postgres" : "SQLite"}</dd></div>
      {#if flights}
        <div class="row" data-testid="flight-status-usage">
          <dt class="text-muted-foreground">Flight status</dt>
          <dd class="font-medium">{flights.enabled ? `${flights.used} of ${flights.limit} calls used this month` : "Off (RAPIDAPI_KEY isn’t set)"}</dd>
        </div>
      {/if}
    </dl>
  </section>
  {:else if tab === "mail"}
    <GmailSection />

    <AiSection />
  {:else if tab === "travel"}
    <RemindersSection />

    <DistanceSection />

    <LogosSection />

    <ImportSection />
  {:else}
    <McpSection />

    <DataSection />
  {/if}
</div>
