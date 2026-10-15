import { describe, expect, it, vi } from "vitest";
import { api, data } from "./api";
import type { TripList, SegmentEmails, Preview } from "../src/lib/api-types";

describe("standalone demo transport", () => {
  it("rejects writes, authentication and integrations without making a request", async () => {
    const request = vi.spyOn(globalThis, "fetch");
    for (const path of ["/api/trips", "/api/segments", "/api/import", "/api/mailboxes/connect", "/auth/logout", "/api/mcp-settings/writes"]) {
      await expect(api(path, { method: "POST", body: {} })).rejects.toMatchObject({status:403});
      await expect(api(path, { method: "DELETE" })).rejects.toMatchObject({status:403});
    }
    expect(request).not.toHaveBeenCalled();
    request.mockRestore();
  });

  it("keeps the bundled household unchanged when a caller modifies a response", async () => {
    const reply = await api<TripList>("/api/trips");
    reply.trips[0].name = "Changed by a caller";
    reply.trips[0].segments.length = 0;
    const again = await api<TripList>("/api/trips");
    expect(again.trips[0].name).toBe(data.trips[0].name);
    expect(again.trips[0].segments.length).toBeGreaterThan(0);
  });

  it("provides a synthetic source email and populated details for every booking", async () => {
    const bookings = data.trips.flatMap(trip=>trip.segments);
    expect(bookings).toHaveLength(31);
    expect(new Set(bookings.map(booking=>booking.kind))).toEqual(new Set(["flight","hotel","car","cruise","parking"]));
    for (const booking of bookings) {
      const reply = await api<SegmentEmails>(`/api/segments/${booking.id}/emails`);
      expect(reply.emails).toHaveLength(1);
      expect(reply.emails[0].text).toContain("SIMULATED BOOKING EMAIL");
      expect(reply.emails[0].text).toContain(booking.confirmation);
      expect(reply.emails[0].images).toBe(0);
      expect(reply.emails[0].html).toBeNull();
      expect(booking.price).not.toBeNull();
      expect(Object.keys(booking.details).length).toBeGreaterThan(1);
    }
  });

  it("contains one shared Camden stay with one price and consistent source details", async () => {
    const london = data.trips.find(trip=>trip.id === 4)!;
    const stays = london.segments.filter(booking=>booking.origin === "Camden Guesthouse");
    expect(stays).toHaveLength(1);
    expect(stays[0].travelers.map(traveler=>traveler.name)).toEqual(["Jane Doe", "Sam Doe", "Mia Doe", "Grandma Joan"]);
    expect(stays[0].price).toMatchObject({amount_minor:31000,currency:"GBP"});
    const email = (await api<SegmentEmails>(`/api/segments/${stays[0].id}/emails`)).emails[0];
    expect(email.text).toContain(stays[0].details.address);
    expect(email.text).toContain("Family suite");
    expect(email.text).toContain("310.00 GBP");
    expect(london.costs.totals.find(total=>total.currency === "GBP")?.amount_minor).toBe(125800);
    const bookings = data.trips.flatMap(trip=>trip.segments).filter(booking=>booking.kind === "hotel");
    const keys = bookings.map(booking=>[booking.origin,booking.confirmation,booking.start_local,booking.end_local].join("|"));
    expect(new Set(keys).size).toBe(bookings.length);
  });

  it("keeps only incomplete flight, road-trip and cruise examples in Review", async () => {
    expect(data.review.items.flatMap(item=>item.suggestions ?? []).map(item=>item.kind)).toEqual(["flight", "car", "cruise"]);
    for (const item of data.review.items) {
      expect(item.reason).toBe("incomplete");
      const preview = await api<Preview>(`/api/review/${item.id}/preview`);
      expect(preview.text).toContain("SIMULATED BOOKING EMAIL");
      for (const booking of item.suggestions ?? []) {
        expect(booking.end_local).toBe("");
        expect(preview.text).toContain(booking.confirmation);
        expect(booking.price_minor).toBeGreaterThan(0);
        expect(booking.price_currency).toBe("USD");
        expect(booking.travelers?.length).toBeGreaterThan(0);
      }
    }
  });

  it("keeps trip people and email aggregates consistent with the bundled bookings", () => {
    expect(data.trips.find(trip=>trip.id === 11)?.people).toEqual([1, 2, 3]);
    expect(data.trips.find(trip=>trip.id === 4)?.emails).toBe(6);
    for (const trip of data.trips) {
      for (const booking of trip.segments) {
        for (const traveler of booking.travelers) {
          if (traveler.person_id !== null) expect(trip.people).toContain(traveler.person_id);
        }
      }
      expect(trip.emails).toBe(trip.segments.reduce((count,booking)=>count+(data.emails[String(booking.id)]?.length ?? 0),0));
    }
  });
});
