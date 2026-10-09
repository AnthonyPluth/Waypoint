import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { boot } from "$lib/app.svelte";
import { clearOnDenied } from "$lib/offline.svelte";

clearOnDenied();
const app = mount(App, { target: document.getElementById("app")! });
boot();

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch((err) => console.warn("Service worker:", err));
}

export default app;
