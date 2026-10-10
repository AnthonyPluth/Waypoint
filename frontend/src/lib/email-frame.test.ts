// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { emailDocument, FRAME_POLICY, FRAME_SANDBOX, PICTURE_TYPES } from "./email-frame";

const png = { type: "image/png", data: "iVBORw0KGgo=" };

describe("emailDocument", () => {
  it("is a complete page with a policy that allows nothing but styles and pictures that came with it", () => {
    const page = emailDocument("<p>Gate B12</p>", []);
    expect(page).toContain(`<meta http-equiv="Content-Security-Policy" content="${FRAME_POLICY}">`);
    expect(FRAME_POLICY).toBe("default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'");
    expect(FRAME_POLICY).not.toMatch(/script|connect|frame|https?:|\*/);
    expect(page).toContain("<p>Gate B12</p>");
    expect(page.startsWith("<!doctype html>")).toBe(true);
  });

  it("gives each picture its place by number, from data the page already holds", () => {
    const page = emailDocument('<img data-image="1" alt="Logo" width="50"><img data-image="0" alt="Banner">', [png, { type: "image/jpeg", data: "/9j/4AAQ" }]);
    expect(page).toContain('<img alt="Logo" width="50" src="data:image/jpeg;base64,/9j/4AAQ">');
    expect(page).toContain('<img alt="Banner" src="data:image/png;base64,iVBORw0KGgo=">');
    expect(page).not.toContain("data-image");
    expect(page).not.toMatch(/src="https?:/);
  });

  it("shows the picture's words when it is missing or isn't one of the four types, and never loads it", () => {
    const hostile = [{ type: "image/svg+xml", data: "PHN2Zz4=" }, { type: "text/html", data: "PGI+" }, { type: "image/png", data: 'AAAA" onerror="x' }, { type: "image/png", data: "AA AA" }];
    const page = emailDocument('<p><img data-image="0" alt="Svg"> <img data-image="1" alt="Html"> <img data-image="2" alt="Quote"> <img data-image="3" alt="Space"> <img data-image="9" alt="Gone"> <img alt="None"></p>', hostile);
    expect(page).toContain("<p>Svg Html Quote Space Gone None</p>");
    expect(page).not.toMatch(/<img|onerror|svg\+xml|text\/html/);
    expect(PICTURE_TYPES).toEqual(["image/png", "image/jpeg", "image/gif", "image/webp"]);
  });

  it("names none of the sandbox's dangerous keywords", () => {
    expect(FRAME_SANDBOX).toBe("allow-popups allow-popups-to-escape-sandbox");
    expect(FRAME_SANDBOX).not.toMatch(/allow-scripts|allow-same-origin|allow-forms|allow-top-navigation/);
  });
});
