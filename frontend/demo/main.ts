import { mount } from "svelte";
import "../src/app.css";
import "./demo.css";
import App from "../src/App.svelte";
import { boot } from "../src/lib/app.svelte";
import { protectDemo } from "./readonly";

protectDemo();
mount(App,{target:document.getElementById("app")!});
void boot();
