/** True on an iPhone or iPad (including an iPad that says it's a Mac): the only place `shoebox://` opens Wallet. */
export function isIOS(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): boolean {
  return /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
}

/** True on a phone or tablet that can have the provider's app (iOS or Android); a desktop browser only has the website. */
export function isMobile(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): boolean {
  return isIOS(nav) || /Android/.test(nav.userAgent);
}
