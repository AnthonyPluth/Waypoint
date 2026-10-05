import { describe, expect, it } from "vitest";
import { isIOS } from "./platform";

const nav = (userAgent: string, platform = "", maxTouchPoints = 0) => ({ userAgent, platform, maxTouchPoints });

describe("isIOS", () => {
  it("is true on an iPhone and an iPad that says it's a Mac", () => {
    expect(isIOS(nav("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"))).toBe(true);
    expect(isIOS(nav("Mozilla/5.0 (Macintosh)", "MacIntel", 5))).toBe(true);
  });
  it("is false on a Mac, Android and Windows", () => {
    expect(isIOS(nav("Mozilla/5.0 (Macintosh)", "MacIntel", 0))).toBe(false);
    expect(isIOS(nav("Mozilla/5.0 (Linux; Android 14)", "Linux armv8l", 5))).toBe(false);
    expect(isIOS(nav("Mozilla/5.0 (Windows NT 10.0)", "Win32"))).toBe(false);
  });
});
