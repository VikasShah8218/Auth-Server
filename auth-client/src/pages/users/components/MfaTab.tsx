import type { UseQueryResult } from "@tanstack/react-query";
import { ShieldCheck, ShieldOff } from "lucide-react";

import type { Schemas } from "@/api/client";
import { FactorRow } from "@/components/common/FactorRow";
import { EmptyState, ErrorState } from "@/components/common/States";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type Factor = Schemas["FactorOut"];

export function MfaTab({
  name,
  query,
  onReset,
}: {
  name: string;
  query: UseQueryResult<Factor[]>;
  onReset: () => void;
}) {
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title="Sign-in factors"
          description={`${name} adds and removes these from the My account page.`}
        />
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : query.isPending ? (
          <div className="p-[18px]">
            <Skeleton className="h-10 w-full" />
          </div>
        ) : query.data.length === 0 ? (
          <EmptyState
            icon={ShieldOff}
            title="MFA is off"
            description={`${name} signs in with a password only. They can add an authenticator app or a security key from My account.`}
          />
        ) : (
          query.data.map((factor) => <FactorRow key={factor.id} factor={factor} />)
        )}
      </Card>

      {query.data && query.data.length > 0 && (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-semibold">Lost device?</h2>
              <p className="mt-0.5 text-fg-2">
                Reset MFA removes every factor and signs {name} out everywhere. MFA is set up again at the
                next sign-in.
              </p>
            </div>
            <Button variant="danger-ghost" onClick={onReset}>
              <ShieldCheck />
              Reset MFA
            </Button>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
