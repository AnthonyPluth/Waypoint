# Standalone static demo

`index.html`, `app.js`, `style.css` and `map.svg` are the complete public payload. All content was invented for this demo, independently of the backend demo generator, uploaded files and databases. No build or backend is needed. Serve this directory with any static HTTP server.

Browse upcoming and past trips (including a flight journey, road trip and cruise), three pending review items, individual itineraries, complete booking details and simulated source emails for every booking, the illustrative SVG map and demo settings. Editing, imports, authentication, mailbox connections and integrations are disabled. There is no persistence, service worker, analytics, remote font or tile service. The Content Security Policy denies all connections.

## GitHub Pages

The existing `Docs` workflow builds documentation into `docs/dist`, then copies only the four demo payload files under `docs/dist/demo/`. It publishes a single combined artifact from `main`. Documentation remains at `/Waypoint/`; the demo is at `/Waypoint/demo/`. Changes to either docs or demo trigger the same workflow. Pull requests build both without publishing. There is no separate deployment from the `demo` branch, so no environment branch exception is needed.

Settings → Pages → Build and deployment → Source must be **GitHub Actions**. Keep the `github-pages` environment allowing `main`. Do not use **Deploy from a branch**: that serves repository source rather than the built documentation site. Nothing has been published by preparing or pushing an integration branch; publication requires merging into main and a successful Docs deploy job.

Run `node demo/verify.mjs` for browser checks at phone, tablet and desktop sizes. It serves only this directory, visits all demo routes and itineraries, fails on external or API requests, browser errors or horizontal overflow, checks disabled controls and records local screenshots under `artifacts/static-demo/`.
