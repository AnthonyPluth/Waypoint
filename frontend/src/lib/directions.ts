import { isIOS } from "$lib/platform";

export type Ride = { id: "apple" | "google" | "uber" | "lyft"; label: string; url: string };

const q = encodeURIComponent;

export function directionsFor(address: string, nav: Pick<Navigator, "userAgent" | "platform" | "maxTouchPoints"> = navigator): Ride[] {
  const a = address.trim();
  const apple = nav.userAgent.includes("Macintosh") || isIOS(nav);
  return [
    ...(apple ? [{ id: "apple" as const, label: "Apple Maps", url: `https://maps.apple.com/?daddr=${q(a)}&dirflg=d` }] : []),
    { id: "google", label: "Google Maps", url: `https://www.google.com/maps/dir/?api=1&destination=${q(a)}` },
    { id: "uber", label: "Uber", url: `https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=${q(a)}&dropoff[nickname]=${q(a.split(",")[0])}` },
    { id: "lyft", label: "Lyft", url: `https://lyft.com/ride?id=lyft&destination[address]=${q(a)}` },
  ];
}
