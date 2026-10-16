<script lang="ts">
  import Building from "@lucide/svelte/icons/building";
  import Car from "@lucide/svelte/icons/car";
  import History from "@lucide/svelte/icons/history";
  import ParkingSquare from "@lucide/svelte/icons/square-parking";
  import Plane from "@lucide/svelte/icons/plane";
  import Ship from "@lucide/svelte/icons/ship";
  import TrainFront from "@lucide/svelte/icons/train-front";

  type TileKind = "flight" | "hotel" | "car" | "train" | "cruise" | "parking" | "visit";

  let { kind, size = 28, decorative = false }: { kind: TileKind; size?: 28 | 36; decorative?: boolean } = $props();

  const ICONS = { flight: Plane, hotel: Building, car: Car, train: TrainFront, cruise: Ship, parking: ParkingSquare, visit: History } as const;
  const NAMES = { flight: "flight", hotel: "stay", car: "rental car", train: "train", cruise: "cruise", parking: "parking", visit: "past visit" } as const;
  const TONES = {
    flight: "bg-kind-flight-soft text-kind-flight",
    hotel: "bg-kind-stay-soft text-kind-stay",
    train: "bg-kind-train-soft text-kind-train",
    car: "bg-kind-car-soft text-kind-car",
    cruise: "bg-kind-quiet-soft text-kind-quiet",
    parking: "bg-kind-quiet-soft text-kind-quiet",
    visit: "bg-kind-quiet-soft text-kind-quiet",
  } as const;
  const Icon = $derived(ICONS[kind]);
</script>

<span
  class={`inline-flex shrink-0 items-center justify-center ${size === 36 ? "size-9 rounded-[10px]" : "size-7 rounded-lg"} ${TONES[kind]}`}
  role={decorative ? undefined : "img"}
  aria-label={decorative ? undefined : NAMES[kind]}
  aria-hidden={decorative ? "true" : undefined}
  data-kind={kind}
>
  <Icon class={size === 36 ? "size-5" : "size-4"} aria-hidden="true" />
</span>
