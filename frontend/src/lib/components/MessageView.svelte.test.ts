// @vitest-environment jsdom
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import MessageView from "./MessageView.svelte";

describe("MessageView", () => {
  it("shows the subject and the text, and says when it was cut short", () => {
    render(MessageView, { subject: "Your itinerary", text: "Gate B12", truncated: true });
    expect(screen.getByTestId("message-subject")).toHaveTextContent("Your itinerary");
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    expect(screen.getByText("Cut short here.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();   // (no HTML part: nothing to switch)
  });

  it("shows markup formatted, with a switch to its plain text and back", async () => {
    render(MessageView, { text: "Gate B12", html: "<p>Gate <b>B12</b></p>" });
    expect(screen.queryByTestId("message-subject")).toBeNull();
    expect(screen.getByTestId("preview-html").querySelector("b")).toHaveTextContent("B12");
    await userEvent.click(screen.getByRole("button", { name: "Show as plain text" }));
    expect(screen.queryByTestId("preview-html")).toBeNull();
    expect(screen.getByText("Gate B12")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as formatted" }));
    expect(screen.getByTestId("preview-html")).toBeInTheDocument();
  });

  it("says when a message has no text", () => {
    render(MessageView, { text: "" });
    expect(screen.getByText("(This message has no text.)")).toBeInTheDocument();
  });
});
