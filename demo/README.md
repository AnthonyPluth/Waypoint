# Standalone static demo

`index.html`, `app.js`, `style.css` and `map.svg` are the complete public payload. All content was invented for this demo, independently of the backend demo generator, uploaded files and databases. No build or backend is needed. Serve this directory with any static HTTP server.

Browse upcoming and past trips (including a flight journey, road trip and cruise), three pending review items, individual itineraries, complete booking details and simulated source emails for every booking, the illustrative SVG map and demo settings. Editing, imports, authentication, mailbox connections and integrations are disabled. There is no persistence, service worker, analytics, remote font or tile service. The Content Security Policy denies all connections.

## GitHub Pages

The `Static demo` workflow runs on the `demo` branch and builds the current `main` documentation into the Pages artifact, then adds only the four demo payload files under `demo/`. The documentation remains at `/Waypoint/`; the demo is served at `/Waypoint/demo/`. The documentation workflow change prepared on this branch also includes the demo in future main deployments and shares the Pages concurrency group. The live main workflow and Pages configuration are not changed by pushing this branch.

Pages must use GitHub Actions, and the `github-pages` environment must permit deployments from `demo`. A successful workflow deployment establishes publication; pushing code alone does not.

The existing `main` documentation deployment publishes its own artifact and can remove `/demo/` on its next run. Until the prepared documentation workflow change is applied to main, rerun `Static demo` after documentation deployments to restore the demo. Both deployments preserve the documentation root. Do not switch Pages to branch hosting or publish only the demo artifact over the documentation site.

Run `node demo/verify.mjs` for browser checks at phone, tablet and desktop sizes. It serves only this directory, visits all demo routes and itineraries, fails on external or API requests, browser errors or horizontal overflow, checks disabled controls and records local screenshots under `artifacts/static-demo/`.

## Publication status

The first deployment built the combined documentation/demo artifact successfully, but GitHub rejected its deploy job because the `github-pages` environment does not allow the `demo` branch. The demo is prepared and pushed, not published. Add `demo` to the environment's allowed deployment branches while retaining `main`, then rerun the latest `Static demo` workflow. The expected demo URL is `https://anthonypluth.github.io/Waypoint/demo/`; it is not evidence of publication until the deploy job succeeds.
