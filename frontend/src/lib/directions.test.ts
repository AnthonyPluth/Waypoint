import { describe, expect, it } from "vitest";
import { directionsFor } from "./directions";

const iphone = { userAgent: "iPhone", platform: "iPhone", maxTouchPoints: 5 };
const android = { userAgent: "Android", platform: "Linux", maxTouchPoints: 5 };
const addr = "1 Main St, Austin, TX 78701";

describe("directionsFor", () => {
  it("offers Apple Maps only on Apple devices", () => {
    expect(directionsFor(addr, iphone).map((r) => r.id)).toEqual(["apple", "google", "uber", "lyft"]);
    expect(directionsFor(addr, android).map((r) => r.id)).toEqual(["google", "uber", "lyft"]);
  });
  it("prefills the encoded address in every link", () => {
    for (const r of directionsFor(addr, iphone)) expect(r.url).toContain(encodeURIComponent(addr));
  });
});
