import { useDownstream } from "@/api/operations";
import { PageHeader } from "@/components/common/PageHeader";
import { SyncTable } from "@/components/common/SyncTable";
import { usePageMeta } from "@/components/layout/page-meta";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";

export default function DownstreamSync() {
  usePageMeta({ label: "Downstream sync" });
  const downstream = useDownstream();

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Downstream sync"
        description="Every running instance of every downstream server, and how far it is behind on revocations. Refreshes every 10 seconds."
      />
      <div className="grid gap-4">
        <SyncTable query={downstream} />
        <Card>
          <CardBody className="grid gap-2.5 text-[13px] text-fg-2 sm:grid-cols-3">
            <p>
              <Badge tone="ok" dot>
                In sync
              </Badge>{" "}
              The instance has applied every event.
            </p>
            <p>
              <Badge tone="warn" dot>
                Behind
              </Badge>{" "}
              Connected, but still applying events.
            </p>
            <p>
              <Badge tone="danger" dot>
                Offline
              </Badge>{" "}
              Not heard from for over a minute. Its tokens still expire on time.
            </p>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
