import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CardFooter } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";

export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number | undefined;
  onChange: (offset: number) => void;
}) {
  const count = total ?? 0;
  const first = count === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, count);
  return (
    <CardFooter>
      <span aria-live="polite">
        Showing{" "}
        <b className="font-medium text-fg-2">
          {count === 0 ? "0" : `${formatNumber(first)}–${formatNumber(last)}`}
        </b>{" "}
        of <b className="font-medium text-fg-2">{formatNumber(count)}</b>
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          <ChevronLeft aria-hidden />
          Previous
        </Button>
        <Button size="sm" disabled={offset + limit >= count} onClick={() => onChange(offset + limit)}>
          Next
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </CardFooter>
  );
}
