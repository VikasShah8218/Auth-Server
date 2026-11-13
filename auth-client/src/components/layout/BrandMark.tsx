import { cn } from "@/lib/cn";

/** Four key teeth in an accent square. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-[30px] shrink-0 items-end justify-center gap-0.5 rounded-control bg-accent pb-[7px]",
        className,
      )}
    >
      {[8, 14, 10, 16].map((height, i) => (
        <i key={i} className="block w-[3px] rounded-[1px] bg-ink" style={{ height }} />
      ))}
    </span>
  );
}
