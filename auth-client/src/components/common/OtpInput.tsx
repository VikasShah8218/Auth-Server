import { useEffect, useRef, type ClipboardEvent, type KeyboardEvent } from "react";

import { cn } from "@/lib/cn";

const LENGTH = 6;

/**
 * Six boxes for a TOTP code. Typing moves forward, Backspace moves back, pasting fills every box.
 * onComplete fires once all six digits are present.
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  autoFocus,
  disabled,
  invalid,
  label = "6-digit code",
}: {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  label?: string;
}) {
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length: LENGTH }, (_, i) => value[i] ?? "");

  useEffect(() => {
    if (autoFocus) boxes.current[0]?.focus();
  }, [autoFocus]);

  function update(next: string) {
    const clean = next.replace(/\D/g, "").slice(0, LENGTH);
    onChange(clean);
    if (clean.length === LENGTH) onComplete?.(clean);
  }

  function setDigit(index: number, digit: string) {
    const chars = digits.slice();
    chars[index] = digit;
    update(chars.join("").replace(/\s/g, ""));
    if (digit && index < LENGTH - 1) boxes.current[index + 1]?.focus();
  }

  function onKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && !digits[index] && index > 0) {
      boxes.current[index - 1]?.focus();
      setDigit(index - 1, "");
      event.preventDefault();
    }
    if (event.key === "ArrowLeft" && index > 0) boxes.current[index - 1]?.focus();
    if (event.key === "ArrowRight" && index < LENGTH - 1) boxes.current[index + 1]?.focus();
  }

  function onPaste(event: ClipboardEvent<HTMLInputElement>) {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, LENGTH);
    if (!pasted) return;
    event.preventDefault();
    update(pasted);
    boxes.current[Math.min(pasted.length, LENGTH - 1)]?.focus();
  }

  return (
    <fieldset className="m-0 border-0 p-0">
      <legend className="sr-only">{label}</legend>
      <div className="grid grid-cols-6 gap-2">
        {digits.map((digit, index) => (
          <input
            key={index}
            ref={(element) => {
              boxes.current[index] = element;
            }}
            value={digit}
            inputMode="numeric"
            autoComplete={index === 0 ? "one-time-code" : "off"}
            maxLength={1}
            disabled={disabled}
            aria-label={`Digit ${index + 1}`}
            aria-invalid={invalid || undefined}
            onChange={(event) => setDigit(index, event.target.value.replace(/\D/g, "").slice(-1))}
            onKeyDown={(event) => onKeyDown(index, event)}
            onPaste={onPaste}
            onFocus={(event) => event.target.select()}
            className={cn(
              "h-[50px] w-full rounded-control border border-line-strong bg-surface text-center font-mono text-xl font-semibold text-fg outline-none",
              "focus:border-accent focus:shadow-[var(--focus-ring)] disabled:opacity-60 aria-invalid:border-danger",
            )}
          />
        ))}
      </div>
    </fieldset>
  );
}
