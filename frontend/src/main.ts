import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { boot } from "$lib/app.svelte";

const app = mount(App, { target: document.getElementById("app")! });
boot();

// Installable app: the service worker shows notifications and keeps the app's shell for offline starts.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch((err) => console.warn("Service worker:", err));
}

export default app;
