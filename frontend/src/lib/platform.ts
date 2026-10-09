export function isIOS(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): boolean {
  return /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
}

export function isMobile(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): boolean {
  return isIOS(nav) || /Android/.test(nav.userAgent);
}

export function deviceCheckName(nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): string {
  if (isIOS(nav)) return "Face ID or Touch ID";
  if (/Macintosh|Mac OS X/.test(nav.userAgent)) return "Touch ID";
  if (/Android/.test(nav.userAgent)) return "your fingerprint or screen lock";
  if (/Windows/.test(nav.userAgent)) return "Windows Hello";
  return "your screen lock";
}
