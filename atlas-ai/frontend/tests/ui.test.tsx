import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ActivityList from "@/components/blocks/ActivityList";
import { Confirm, SignalChip, Toggle } from "@/components/ui";

describe("ui", () => {
  it("renders signal classifications", () => {
    render(<SignalChip value="STRONG BUY CANDIDATE" />);
    expect(screen.getByText("STRONG BUY CANDIDATE")).toBeTruthy();
  });
  it("requires confirmation before destructive actions", async () => {
    const fn = vi.fn();
    render(<Confirm label="Close" confirmLabel="Close at market" onConfirm={fn} />);
    fireEvent.click(screen.getByText("Close"));
    expect(fn).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Close at market"));
    expect(fn).toHaveBeenCalledOnce();
  });
  it("toggles", () => {
    const fn = vi.fn();
    render(<Toggle checked={false} onChange={fn} label="x" />);
    fireEvent.click(screen.getByRole("switch"));
    expect(fn).toHaveBeenCalledWith(true);
  });
  it("renders activity with explanations and escapes content", () => {
    render(<ActivityList rows={[{ id: 1, ts: new Date().toISOString(), kind: "risk", symbol: "SOLUSDC", message: "Rejecting <b>trade</b>", explanation: "insufficient liquidity", data: {} }]} />);
    expect(screen.getByText("Rejecting <b>trade</b>")).toBeTruthy();
    expect(screen.getByText("insufficient liquidity")).toBeTruthy();
  });
});
