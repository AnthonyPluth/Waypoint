import { airportInfo } from "./airport-zones";

export function cityNames(codes: () => (string | null | undefined)[]): Record<string, string> {
  const cities = $state<Record<string, string>>({});
  $effect(() => {
    const wanted = codes().filter((c): c is string => !!c);
    let current = true;
    for (const code of wanted) {
      void airportInfo(code).then((airport) => { if (current && airport) cities[code] = airport.city || airport.name; });
    }
    return () => { current = false; };
  });
  return cities;
}
