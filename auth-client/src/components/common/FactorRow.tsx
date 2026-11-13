import { KeyRound, Smartphone } from "lucide-react";
import type { ReactNode } from "react";

import type { Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/format";

import { ListRow, Tile } from "./ListRow";

type Factor = Schemas["FactorOut"];

export function FactorRow({ factor, action }: { factor: Factor; action?: ReactNode }) {
  const totp = factor.type === "totp";
  return (
    <ListRow
      leading={<Tile>{totp ? <Smartphone /> : <KeyRound />}</Tile>}
      title={
        <>
          {totp ? "Authenticator app" : factor.name || "Security key"}
          <Badge tone="ok">On</Badge>
        </>
      }
      meta={`${totp ? "6-digit codes" : "Security key"} · added ${formatDate(factor.confirmed_at)}`}
      action={action}
    />
  );
}
