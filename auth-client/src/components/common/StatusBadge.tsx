import { Badge, type BadgeTone } from "@/components/ui/badge";

const STATUS: Record<string, { tone: BadgeTone; label: string }> = {
  active: { tone: "ok", label: "Active" },
  disabled: { tone: "neutral", label: "Disabled" },
  ok: { tone: "ok", label: "In sync" },
  lagging: { tone: "warn", label: "Behind" },
  offline: { tone: "danger", label: "Offline" },
  next: { tone: "info", label: "Next" },
  retired: { tone: "neutral", label: "Retired" },
  expired: { tone: "neutral", label: "Expired" },
  revoked: { tone: "danger", label: "Revoked" },
};

/** One place that decides how a status looks and is named. */
export function StatusBadge({ status }: { status: string }) {
  const known = STATUS[status] ?? { tone: "neutral" as const, label: status };
  return (
    <Badge tone={known.tone} dot>
      {known.label}
    </Badge>
  );
}
