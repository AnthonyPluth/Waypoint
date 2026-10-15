<script lang="ts">
  import { act } from "$lib/act";
  import { api } from "$lib/api";
  import { app, route } from "$lib/app.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import AiSection from "$lib/components/settings/AiSection.svelte";
  import CostsSection from "$lib/components/settings/CostsSection.svelte";
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
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import UserRound from "@lucide/svelte/icons/user-round";
  import Mail from "@lucide/svelte/icons/mail";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import Bell from "@lucide/svelte/icons/bell";
  import Bot from "@lucide/svelte/icons/bot";
  import Archive from "@lucide/svelte/icons/archive";

  const s = $derived(app.state);
  const user = $derived(s?.user);
  let signingOut = $state(false);
  const flights = $derived(flightStatus.list);
  onMount(loadFlightStatus);
  onMount(() => {
    if (landing && !route.sub) {
      history.replaceState(history.state, "", `${location.pathname}${location.search}#settings/${landing}`);
      route.sub = landing;
      landing = "";
    }
  });

  const GROUPS = [
    { id: "account", label: "Account", icon: UserRound, about: "Your profile and app information." },
    { id: "mail", label: "Mail & review", icon: Mail, about: "Connected mailboxes, email preferences and AI booking extraction." },
    { id: "travel", label: "Travel preferences", icon: SlidersHorizontal, about: "Your home, distance units, trip costs and booking logos." },
    { id: "offline", label: "Offline & notifications", icon: Bell, about: "Saved trips, travel reminders and your calendar subscription." },
    { id: "assistants", label: "Connected assistants", icon: Bot, about: "Manage your assistants and choose what they can access." },
    { id: "backup", label: "Backup & import", icon: Archive, about: "Keep a backup, restore your data or bring in past flights." },
  ] as const;
  type Group = (typeof GROUPS)[number]["id"];
  const OLD_LINKS: Record<string, Group> = { data: "backup" };
  let landing = $state<Group | "">(new URLSearchParams(location.search).has("gmail") ? "mail" : "");
  const sub = $derived(OLD_LINKS[route.sub] ?? route.sub);
  const group = $derived<(typeof GROUPS)[number] | undefined>(GROUPS.find((g) => g.id === sub) ?? GROUPS.find((g) => g.id === landing));

  const signOut = () => act(async () => {
    await clearSaved();
    const r = await api<{ redirect: string }>("/auth/logout", { method: "POST" });
    location.href = r.redirect;
  }, { busy: (on) => (signingOut = on) });
</script>

<div class="mb-8">
  <p class="eyebrow mb-2 text-primary">Make Waypoint yours</p>
  <h1 class="text-display">{group ? group.label : "Settings"}</h1>
  <p class="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">{group ? group.about : "A few preferences for smoother travels. Manage your account, connections and the details that make Waypoint work for you."}</p>
</div>

<div class={group ? "grid min-w-0 gap-6 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-8" : ""}>
  <nav aria-label="Settings sections" class={group ? "min-w-0 lg:sticky lg:top-6 lg:self-start" : ""}>
    {#if group}
      <a href="#settings" class="mb-3 inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"><ChevronLeft class="size-4" aria-hidden="true" />All settings</a>
      <ul class="hidden space-y-1 rounded-2xl border border-border bg-card p-2 lg:block">
        {#each GROUPS as g (g.id)}
          {@const Icon = g.icon}
          <li><a href={`#settings/${g.id}`} aria-current={group.id === g.id ? "page" : undefined} class={`flex min-h-12 items-center gap-3 rounded-xl px-3 py-3 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 ${group.id === g.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}><Icon class="size-4 shrink-0" aria-hidden="true" />{g.label}</a></li>
        {/each}
      </ul>
    {:else}
      <ul class="grid gap-4 md:grid-cols-2">
        {#each GROUPS as g (g.id)}
          {@const Icon = g.icon}
          <li>
            <a href={`#settings/${g.id}`} aria-labelledby={`settings-${g.id}`} aria-describedby={`settings-${g.id}-about`} class="group flex h-full items-start gap-4 rounded-2xl border border-border bg-card p-5 shadow-card outline-none transition-colors hover:border-primary/40 hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 sm:p-6">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Icon class="size-5" aria-hidden="true" /></span>
              <div class="min-w-0 flex-1">
                <h2 id={`settings-${g.id}`} class="font-medium">{g.label}</h2>
                <p id={`settings-${g.id}-about`} class="mt-2 text-sm leading-relaxed text-muted-foreground">{g.about}</p>
              </div>
              <ChevronRight class="mt-3 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" aria-hidden="true" />
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </nav>

{#if group}
<div class="min-w-0 space-y-8">
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

    <CostsSection />

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
</div>
