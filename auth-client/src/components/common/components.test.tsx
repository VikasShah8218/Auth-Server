import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { heldSummary, KeyCut } from "./KeyCut";
import { OtpInput } from "./OtpInput";

const BITS = [
  { code: "*", bit: 0, retired: false, held: false },
  { code: "vehicle.read", bit: 1, retired: false, held: true },
  { code: "vehicle.write", bit: 2, retired: false, held: false },
  { code: "old.thing", bit: 3, retired: true, held: false },
];

describe("KeyCut", () => {
  it("draws one tooth per bit and names the held ones for screen readers", () => {
    render(<KeyCut bits={BITS} />);
    expect(screen.getByRole("list", { name: "Access key. Holds vehicle.read" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "old.thing, bit 3, retired" })).toHaveAttribute(
      "data-retired",
      "true",
    );
  });

  it("names a tooth on focus", () => {
    render(<KeyCut bits={BITS} meta="summary" />);
    expect(screen.getByText("summary")).toBeInTheDocument();
    fireEvent.focus(screen.getByRole("button", { name: /vehicle.write/ }));
    expect(screen.getByText("vehicle.write")).toBeInTheDocument();
    expect(screen.getByText(/bit 2 · not held/)).toBeInTheDocument();
  });

  it("summarises held permissions, ignoring * and retired bits", () => {
    expect(heldSummary(BITS)).toBe("1 of 2 permissions");
    expect(heldSummary([{ ...BITS[0], held: true }, BITS[1]])).toBe("Full access");
  });
});

function Otp({ onComplete }: { onComplete: (code: string) => void }) {
  const [value, setValue] = useState("");
  return <OtpInput value={value} onChange={setValue} onComplete={onComplete} />;
}

describe("OtpInput", () => {
  it("moves forward while typing and completes at six digits", async () => {
    const onComplete = vi.fn();
    render(<Otp onComplete={onComplete} />);
    await userEvent.click(screen.getByLabelText("Digit 1"));
    await userEvent.keyboard("12a3456");
    expect(onComplete).toHaveBeenCalledWith("123456");
  });

  it("fills every box from a paste", async () => {
    const onComplete = vi.fn();
    render(<Otp onComplete={onComplete} />);
    await userEvent.click(screen.getByLabelText("Digit 1"));
    await userEvent.paste("987 654");
    expect(onComplete).toHaveBeenCalledWith("987654");
    expect(screen.getByLabelText("Digit 6")).toHaveValue("4");
  });
});
