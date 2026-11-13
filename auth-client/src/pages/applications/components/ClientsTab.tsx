import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";

import { useClients } from "@/api/clients";
import { ClientsTable } from "@/components/common/ClientsTable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";

export function ClientsTab({ appKey }: { appKey: string }) {
  const clients = useClients(appKey);
  return (
    <Card>
      <CardHeader
        title="Clients"
        description="Browser apps and servers that get tokens for this application."
        actions={
          <Button asChild size="sm" variant="ghost">
            <Link to="/clients" search={{ app: appKey }}>
              Manage clients
              <ChevronRight />
            </Link>
          </Button>
        }
      />
      <ClientsTable query={clients} />
    </Card>
  );
}
