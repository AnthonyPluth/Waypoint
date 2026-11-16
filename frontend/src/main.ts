import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { boot } from "$lib/app.svelte";
import { clearOnDenied } from "$lib/offline.svelte";
import { registerShellCache } from "$lib/shell-cache";

clearOnDenied();
const app = mount(App, { target: document.getElementById("app")! });
boot();

if ("serviceWorker" in navigator && window.isSecureContext) {
  registerShellCache(navigator.serviceWorker, window);
}

export default app;
