<script lang="ts">
  import { ignoreFailure } from "$lib/act";
  import { signInUrl } from "$lib/api";
  import { app, boot, route } from "$lib/app.svelte";
  import SideNav from "$lib/components/SideNav.svelte";
  import TabBar from "$lib/components/TabBar.svelte";
  import TopBar from "$lib/components/TopBar.svelte";
  import { Button } from "$lib/components/ui/button";
  import OfflineApp from "$lib/components/OfflineApp.svelte";
  import * as Alert from "$lib/components/ui/alert";
  import * as Card from "$lib/components/ui/card";
  import { pageFor } from "$lib/nav";
  import Upcoming from "./pages/Upcoming.svelte";
  import { Toaster } from "svelte-sonner";
  import type { Component } from "svelte";

  const LAZY: Record<string, () => Promise<{ default: Component }>> = {
    trips: () => import("./pages/Trips.svelte"), stats: () => import("./pages/Stats.svelte"), trip: () => import("./pages/Trip.svelte"),
    people: () => import("./pages/People.svelte"), review: () => import("./pages/Review.svelte"), settings: () => import("./pages/Settings.svelte"),
    design: () => import("./pages/Design.svelte"),
  };
  const loaded: Record<string, Component> = { upcoming: Upcoming };
  let Page = $state<Component | null>(null);
  let pageFailed = $state(false);

  $effect(() => {
    const key = pageFor(route.page);
    pageFailed = false;
    if (loaded[key]) { Page = loaded[key]; return; }
    Page = null;
    let current = true;
    LAZY[key]().then((m) => { loaded[key] = m.default; if (current) Page = m.default; }, () => { if (current) pageFailed = true; });
    return () => { current = false; };
  });

  function whenIdle(run: () => void): () => void {
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(run, { timeout: 5000 });
      return () => window.cancelIdleCallback(handle);
    }
    const handle = window.setTimeout(run, 2000);
    return () => window.clearTimeout(handle);
  }

  $effect(() => {
    if (!app.state) return;
    return whenIdle(() => Object.values(LAZY).forEach((load) => void load().catch(ignoreFailure)));
  });
</script>

<div class="flex min-h-dvh flex-col">
  <TopBar />
  <div class="flex flex-1">
    <SideNav />
    <main class="min-w-0 flex-1 px-4 pt-6 pb-[calc(env(safe-area-inset-bottom)+6rem)] md:px-8 md:pt-8 lg:pb-12">
      <div class={`mx-auto max-w-3xl ${route.page === "trips" ? "lg:max-w-6xl" : ""}`}>
        {#if app.sessionExpired}
          <Alert.Root class="sticky top-[calc(env(safe-area-inset-top)+4rem)] z-20 mb-4 flex flex-wrap items-center justify-between gap-3 border-signal bg-signal-soft text-signal-ink shadow-lg">
            <Alert.Description class="text-signal-ink">Your session expired. Sign in again — what you’re editing stays on this page until you do.</Alert.Description>
            <Button size="sm" onclick={() => { location.href = signInUrl(); }}>Sign in</Button>
          </Alert.Root>
        {/if}
        {#if app.bootError && !app.state && app.offline}
          <OfflineApp />
        {:else if app.bootError && !app.state}
          <Card.Root class="mx-auto mt-10 max-w-md">
            <Card.Header>
              <Card.Title>Can’t reach Waypoint</Card.Title>
              <Card.Description>{app.bootError}</Card.Description>
            </Card.Header>
            <Card.Content><Button variant="outline" onclick={boot}>Try again</Button></Card.Content>
          </Card.Root>
        {:else if app.state && pageFailed}
          <Card.Root class="mx-auto mt-10 max-w-md">
            <Card.Header>
              <Card.Title>Couldn’t load this page</Card.Title>
              <Card.Description>Check your connection, or reload if Waypoint was just updated.</Card.Description>
            </Card.Header>
            <Card.Content><Button variant="outline" onclick={() => location.reload()}>Reload</Button></Card.Content>
          </Card.Root>
        {:else if app.state && Page}
          <Page />
        {:else}
          <div class="space-y-4" aria-busy="true" aria-label="Loading">
            <div class="h-9 w-48 animate-pulse rounded-lg bg-muted motion-reduce:animate-none"></div>
            <div class="h-56 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none"></div>
          </div>
        {/if}
      </div>
    </main>
  </div>
</div>
<TabBar />
<Toaster theme="dark" position="bottom-center" mobileOffset={{ bottom: "calc(env(safe-area-inset-bottom) + 5rem)" }} />
