<script lang="ts">
  import { signInUrl } from "$lib/api";
  import { app, boot, route } from "$lib/app.svelte";
  import SideNav from "$lib/components/SideNav.svelte";
  import TabBar from "$lib/components/TabBar.svelte";
  import TopBar from "$lib/components/TopBar.svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Alert from "$lib/components/ui/alert";
  import * as Card from "$lib/components/ui/card";
  import { pageFor } from "$lib/nav";
  import Settings from "./pages/Settings.svelte";
  import Upcoming from "./pages/Upcoming.svelte";
  import { Toaster } from "svelte-sonner";
  import type { Component } from "svelte";

  // A route's page, by the names in lib/nav.ts. Anything else (an old bookmark, a typo) opens Upcoming.
  const PAGES: Record<string, Component> = { upcoming: Upcoming, settings: Settings };
  const Page = $derived(PAGES[pageFor(route.page)]);
</script>

<div class="flex min-h-dvh flex-col">
  <TopBar />
  <div class="flex flex-1">
    <SideNav />
    <main class="min-w-0 flex-1 px-4 pt-6 pb-[calc(env(safe-area-inset-bottom)+6rem)] md:px-8 md:pt-8 lg:pb-12">
      <div class="mx-auto max-w-3xl">
        {#if app.sessionExpired}
          <!-- Above the page, which stays drawn underneath, so an open edit isn't lost; signing in is up to you. -->
          <Alert.Root class="sticky top-[calc(env(safe-area-inset-top)+4rem)] z-20 mb-4 flex flex-wrap items-center justify-between gap-3 border-signal bg-signal-soft text-signal-ink shadow-lg">
            <Alert.Description class="text-signal-ink">Your session expired. Sign in again — what you’re editing stays on this page until you do.</Alert.Description>
            <Button size="sm" onclick={() => { location.href = signInUrl(); }}>Sign in</Button>
          </Alert.Root>
        {/if}
        {#if app.bootError && !app.state}
          <Card.Root class="mx-auto mt-10 max-w-md">
            <Card.Header>
              <Card.Title>Can’t reach Waypoint</Card.Title>
              <Card.Description>{app.bootError}</Card.Description>
            </Card.Header>
            <Card.Content><Button variant="outline" onclick={boot}>Try again</Button></Card.Content>
          </Card.Root>
        {:else if app.state}
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
<Toaster theme="system" position="bottom-center" mobileOffset={{ bottom: "calc(env(safe-area-inset-bottom) + 5rem)" }} />
