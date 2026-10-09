import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const AXE_SOURCE = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");
export const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
export const AXE_OFF = ["region", "landmark-one-main", "page-has-heading-one", "landmark-unique", "scrollable-region-focusable"];
export const MIN_TAP = 44;
export const MAX_TABS = 80;

export const axeProblems = (violations) => violations.flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.target.join(" ")} (${v.help})`));

export function tapProblems(boxes, viewport) {
  if (viewport !== "phone") return [];
  return boxes.filter((b) => b.width < MIN_TAP || b.height < MIN_TAP).map((b) => `tap-target: ${b.target} is ${Math.round(b.width)}×${Math.round(b.height)} px, under ${MIN_TAP}`);
}

export function focusProblems(stops) {
  return stops.filter((s) => !s.ringed).map((s) => `focus: ${s.target} shows no focus ring`);
}

export async function runAxe(page) {
  await page.evaluate(AXE_SOURCE);
  const result = await page.evaluate(async ({ tags, off }) => globalThis.axe.run(document, { runOnly: { type: "tag", values: tags }, rules: Object.fromEntries(off.map((id) => [id, { enabled: false }])) }), { tags: AXE_TAGS, off: AXE_OFF });
  return axeProblems(result.violations);
}

export async function tapBoxes(page) {
  return page.evaluate(() => {
    const name = (el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}${[...el.classList].slice(0, 2).map((c) => `.${c}`).join("")} "${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 24)}"`;
    const inline = (el) => el.tagName === "A" && getComputedStyle(el).display === "inline" && !!el.closest("p, li, span, td");
    const box = (el) => (el.matches("input[type=checkbox], input[type=radio]") ? el.closest("label") ?? el : el);
    return [...document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=link], [tabindex]:not([tabindex='-1'])")]
      .filter((el) => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return s.visibility !== "hidden" && s.display !== "none" && !el.disabled && r.width > 0 && r.height > 0 && !el.closest(".sr-only, [aria-hidden=true], svg") && !inline(el) && !(el.classList.contains("sr-only")); })
      .map((el) => { const r = box(el).getBoundingClientRect(); return { target: name(el), width: r.width, height: r.height }; });
  });
}

export async function focusStops(page) {
  await page.evaluate(() => { document.activeElement?.blur?.(); window.scrollTo(0, 0); });
  const stops = [];
  const seen = new Set();
  for (let i = 0; i < MAX_TABS; i++) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return null;
      const s = getComputedStyle(el);
      const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0 && s.outlineColor !== "rgba(0, 0, 0, 0)";
      const shadow = s.boxShadow !== "none" && /\d/.test(s.boxShadow.replace(/rgba?\([^)]*\)/g, ""));
      const label = `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""} "${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 24)}"`;
      return { key: label + [...document.querySelectorAll(el.tagName)].indexOf(el), target: label, ringed: outline || shadow };
    });
    if (!stop) break;
    if (seen.has(stop.key)) break;
    seen.add(stop.key);
    stops.push(stop);
  }
  return stops;
}

export async function auditPage(page, viewport) {
  const found = [...(await runAxe(page)), ...tapProblems(await tapBoxes(page), viewport), ...focusProblems(await focusStops(page))];
  return [...new Set(found)];
}

export async function animationsRunning(page) {
  return page.evaluate(() => document.getAnimations().filter((a) => (a.effect?.getComputedTiming().duration ?? 0) > 1 && a.effect?.getComputedTiming().iterations !== 0).map((a) => `${a.animationName ?? a.transitionProperty ?? "animation"} ${Math.round(a.effect.getComputedTiming().duration)} ms`));
}
