<script lang="ts">
  import { act } from "$lib/act";
  import { api } from "$lib/api";
  import { app } from "$lib/app.svelte";
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

  const s = $derived(app.state);
  const user = $derived(s?.user);
  let signingOut = $state(false);
  const flights = $derived(flightStatus.list);
  onMount(loadFlightStatus);

  // The server ends the session and says where to go next (the sign-in provider's own sign-out page, or Waypoint's).
  const signOut = () => act(async () => {
    const r = await api<{ redirect: string }>("/auth/logout", { method: "POST" });
    location.href = r.redirect;
  }, { busy: (on) => (signingOut = on) });
</script>

<h1 class="mb-6 text-4xl font-bold tracking-tight">Settings</h1>

<div class="space-y-8">
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

  <GmailSection />

  <ImportSection />

  <DistanceSection />

  <AiSection />

  <LogosSection />

  <RemindersSection />

  <McpSection />

  <DataSection />
</div>
