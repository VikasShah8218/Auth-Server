import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export type KeyBit = { code: string; bit: number; retired: boolean; held: boolean };

/**
 * The signature element: an application's permission map drawn as the teeth of a key. One tooth per bit,
 * in bit order. A held bit is cut tall in the accent colour, bit 0 is "*" (full access), retired bits are
 * hatched. Hovering or focusing a tooth names it in the caption below.
 */
export function KeyCut({
  bits,
  meta,
  label,
  className,
}: {
  bits: KeyBit[];
  meta?: ReactNode;
  /** Accessible name; defaults to "Access key. Holds …" (one person's access). */
  label?: string;
  className?: string;
}) {
  const [active, setActive] = useState<KeyBit | null>(null);
  const held = bits.filter((b) => b.held).map((b) => b.code);

  return (
    <div className={cn("min-w-0", className)}>
      <ul
        className="keycut m-0 list-none"
        aria-label={
          label ?? (held.length ? `Access key. Holds ${held.join(", ")}` : "Access key. Holds no permissions")
        }
      >
        {bits.map((b) => (
          <li key={b.bit} className="contents">
            <button
              type="button"
              className="keycut-bit cursor-default border-0 p-0"
              data-held={b.held}
              data-retired={b.retired}
              data-wild={b.bit === 0}
              aria-label={`${b.code}, bit ${b.bit}, ${b.retired ? "retired" : b.held ? "held" : "not held"}`}
              onMouseEnter={() => setActive(b)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(b)}
              onBlur={() => setActive(null)}
            />
          </li>
        ))}
      </ul>
      <div
        className="mt-2 flex min-h-[18px] flex-wrap gap-3.5 font-mono text-[11.5px] text-muted"
        aria-live="polite"
      >
        {active ? (
          <span>
            <b className="font-medium text-fg-2">{active.code}</b> · bit {active.bit}
            {active.retired ? " · retired" : active.held ? " · held" : " · not held"}
          </span>
        ) : (
          meta
        )}
      </div>
    </div>
  );
}

/** "4 of 8 permissions": retired bits and "*" don't count; holding "*" is full access. */
export function heldSummary(bits: KeyBit[]): string {
  if (bits.some((b) => b.bit === 0 && b.held)) return "Full access";
  const live = bits.filter((b) => !b.retired && b.bit !== 0);
  const held = live.filter((b) => b.held).length;
  return `${held} of ${live.length} permission${live.length === 1 ? "" : "s"}`;
}
