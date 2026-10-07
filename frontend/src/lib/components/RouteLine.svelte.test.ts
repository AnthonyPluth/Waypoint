// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { segment } from "../../test/fixtures";
import RouteLine from "./RouteLine.svelte";

const plane = () => screen.getByTestId("route-plane");
const fill = () => screen.getByTestId("route-fill");

describe("the route line", () => {
  it("shows both airport codes and reads as the route", () => {
    render(RouteLine, { segment: segment() });
    expect(screen.getByTestId("route-line")).toHaveTextContent("JFK → LHR");
    expect(screen.getAllByTestId("airport-code").map((code) => code.textContent)).toEqual(["JFK", "LHR"]);
    expect(screen.getByTestId("route-line")).toBeInTheDocument();
  });

  it("draws the route for a train too", () => {
    render(RouteLine, { segment: segment({ kind: "train", origin: "NYP", destination: "BOS" }) });
    expect(screen.getByTestId("route-line")).toHaveTextContent("NYP → BOS");
  });

  it("sits at the origin with no value", () => {
    render(RouteLine, { segment: segment() });
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "0");
    expect(fill().style.width).toBe("0%");
    expect(plane().style.left).toBe("0%");
  });

  it("sits at the origin at progress 0", () => {
    render(RouteLine, { segment: segment(), progress: 0 });
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "0");
    expect(fill().style.width).toBe("0%");
    expect(plane().style.left).toBe("0%");
  });

  it("puts the plane halfway along at progress 0.5, filled behind it", () => {
    render(RouteLine, { segment: segment(), progress: 0.5 });
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "0.5");
    expect(fill().style.width).toBe("50%");
    expect(plane().style.left).toBe("50%");
  });

  it("lands the plane at the destination at progress 1", () => {
    render(RouteLine, { segment: segment(), progress: 1 });
    expect(screen.getByTestId("route-line")).toHaveAttribute("data-progress", "1");
    expect(fill().style.width).toBe("100%");
    expect(plane().style.left).toBe("100%");
  });

  it("keeps a value outside 0 to 1 on the line", () => {
    const { rerender } = render(RouteLine, { segment: segment(), progress: 1.4 });
    expect(fill().style.width).toBe("100%");
    expect(plane().style.left).toBe("100%");
    rerender({ segment: segment(), progress: -0.4 });
    expect(fill().style.width).toBe("0%");
    expect(plane().style.left).toBe("0%");
  });

  it("writes the headline for a segment with no route", () => {
    const stay = segment({ kind: "hotel", origin: "London", provider: "Harbour Hotel", destination: null });
    render(RouteLine, { segment: stay });
    expect(screen.queryByTestId("route-line")).toBeNull();
    expect(screen.getByText("London")).toBeInTheDocument();
    render(RouteLine, { segment: segment({ kind: "cruise", origin: "Miami", details: { ship: "Example Voyager" } }) });
    expect(screen.queryByTestId("route-line")).toBeNull();
    expect(screen.getByText("Example Voyager · Miami")).toBeInTheDocument();
  });
});
