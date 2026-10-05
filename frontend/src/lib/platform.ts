/** True on an iPhone or iPad (including an iPad that says it's a Mac): the only place `shoebox://` opens Wallet. */
export function isIOS(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): boolean {
  return /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
}
