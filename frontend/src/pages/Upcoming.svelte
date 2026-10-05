<script lang="ts">
  import PlaneTakeoff from "@lucide/svelte/icons/plane-takeoff";
</script>

<h1 class="mb-6 text-3xl font-semibold tracking-tight">Upcoming</h1>

<!-- Nothing to show until trips exist: no sample data, just where they'll go. -->
<section class="pass" aria-labelledby="empty-title">
  <div class="flex flex-col items-start gap-4 p-6 md:p-8">
    <span class="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary"><PlaneTakeoff class="size-6" aria-hidden="true" /></span>
    <div class="space-y-1.5">
      <p class="eyebrow">Next trip</p>
      <h2 id="empty-title" class="text-xl font-semibold tracking-tight">No trips yet</h2>
      <p class="max-w-prose leading-relaxed text-muted-foreground">No trips yet — they’ll appear here once Waypoint can read your confirmation emails, or when you add one.</p>
    </div>
  </div>
  <div class="pass-tear" aria-hidden="true"></div>
  <!-- The stub: a route with nothing filled in yet. -->
  <div class="flex items-center gap-3 px-6 py-5 text-muted-foreground md:px-8" aria-hidden="true">
    <span class="code text-lg">- - -</span>
    <span class="h-px flex-1 border-t-2 border-dotted border-border"></span>
    <PlaneTakeoff class="size-5" />
    <span class="h-px flex-1 border-t-2 border-dotted border-border"></span>
    <span class="code text-lg">- - -</span>
  </div>
</section>
