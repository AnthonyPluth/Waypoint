<script lang="ts">
  import Bed from "@lucide/svelte/icons/bed";
  import Car from "@lucide/svelte/icons/car";
  import History from "@lucide/svelte/icons/history";
  import ParkingSquare from "@lucide/svelte/icons/square-parking";
  import Plane from "@lucide/svelte/icons/plane";
  import Ship from "@lucide/svelte/icons/ship";
  import TrainFront from "@lucide/svelte/icons/train-front";

  type TileKind = "flight" | "hotel" | "car" | "train" | "cruise" | "parking" | "visit";

  let { kind, size = 28, decorative = false, outline = false }: { kind: TileKind; size?: 28 | 34 | 36 | 40 | 44; decorative?: boolean; outline?: boolean } = $props();

  const ICONS = { flight: Plane, hotel: Bed, car: Car, train: TrainFront, cruise: Ship, parking: ParkingSquare, visit: History } as const;
  const NAMES = { flight: "flight", hotel: "stay", car: "rental car", train: "train", cruise: "cruise", parking: "parking", visit: "past visit" } as const;
  const TONES = {
    flight: "bg-kind-flight-soft text-kind-flight",
    hotel: "bg-kind-stay-soft text-kind-stay",
    train: "bg-kind-train-soft text-kind-train",
    car: "bg-kind-car-soft text-kind-car",
    cruise: "bg-kind-cruise-soft text-kind-cruise",
    parking: "bg-kind-parking-soft text-kind-parking",
    visit: "bg-kind-quiet-soft text-kind-quiet",
  } as const;
  const INKS = {
    flight: "text-kind-flight",
    hotel: "text-kind-stay",
    train: "text-kind-train",
    car: "text-kind-car",
    cruise: "text-kind-cruise",
    parking: "text-kind-parking",
    visit: "text-kind-quiet",
  } as const;
  const Icon = $derived(ICONS[kind]);
</script>

<span
  class={`inline-flex shrink-0 items-center justify-center ${outline ? INKS[kind] : `${TONES[kind]} ${size === 44 ? "size-11 rounded-[13px]" : size === 40 ? "size-10 rounded-xl" : size === 36 ? "size-9 rounded-[10px]" : size === 34 ? "size-[34px] rounded-[10px]" : "size-7 rounded-lg"}`}`}
  role={decorative ? undefined : "img"}
  aria-label={decorative ? undefined : NAMES[kind]}
  aria-hidden={decorative ? "true" : undefined}
  data-tile={kind}
>
  <Icon class={outline ? "size-[26px]" : size === 28 ? "size-4" : "size-5"} stroke-width={outline ? 1.9 : undefined} aria-hidden="true" />
</span>
