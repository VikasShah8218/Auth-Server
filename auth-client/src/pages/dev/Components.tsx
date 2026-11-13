/** Development only: every shared component in its states, for side-by-side review with ui-design/. */
import { Activity, AppWindow, Plug, Plus, ScrollText, Search, Trash2, Users } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { DataTable } from "@/components/common/DataTable";
import { FormField } from "@/components/common/FormField";
import { KeyCut } from "@/components/common/KeyCut";
import { OtpInput } from "@/components/common/OtpInput";
import { PageHeader } from "@/components/common/PageHeader";
import { StatStrip } from "@/components/common/StatStrip";
import { EmptyState } from "@/components/common/States";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const BITS = [
  { code: "*", bit: 0, retired: false, held: false },
  { code: "vehicle.read", bit: 1, retired: false, held: true },
  { code: "vehicle.write", bit: 2, retired: false, held: true },
  { code: "camera.read", bit: 3, retired: false, held: true },
  { code: "report.view", bit: 4, retired: false, held: true },
  { code: "report.export", bit: 5, retired: false, held: false },
  { code: "watchlist.edit", bit: 6, retired: false, held: false },
  { code: "alpr.legacy", bit: 7, retired: true, held: false },
  { code: "settings.edit", bit: 8, retired: false, held: false },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody className="flex flex-wrap items-center gap-3">{children}</CardBody>
    </Card>
  );
}

export default function Components() {
  const [code, setCode] = useState("");
  const [confirm, setConfirm] = useState(false);

  return (
    <div className="mx-auto grid max-w-[1100px] gap-4 p-6">
      <PageHeader
        eyebrow="Development"
        title="Components"
        description="Compare with ui-design/ in both themes and at phone width."
        actions={<ThemeToggle />}
      />
      <StatStrip
        stats={[
          { label: "Users", icon: Users, value: 128, note: "6 disabled" },
          { label: "Applications", icon: AppWindow, value: 4, note: "AUTH, ANPR, SNVR, GATE" },
          { label: "Live sessions", icon: Activity, value: 37, note: "across 29 people" },
          { label: "Service clients", icon: Plug, value: 5, note: "active" },
        ]}
      />
      <Section title="Buttons">
        <Button variant="primary">
          <Plus />
          Primary
        </Button>
        <Button>Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button variant="danger-ghost">Danger ghost</Button>
        <Button size="sm">Small</Button>
        <Button size="icon" aria-label="Search">
          <Search />
        </Button>
        <Button loading>Saving</Button>
        <Button disabled>Disabled</Button>
      </Section>
      <Section title="Badges and chips">
        <StatusBadge status="active" />
        <StatusBadge status="lagging" />
        <StatusBadge status="offline" />
        <StatusBadge status="disabled" />
        <Badge tone="info">Server</Badge>
        <Badge tone="accent">Operator</Badge>
        <Chip>ANPR</Chip>
        <Chip>vehicle.read</Chip>
        <Avatar>AR</Avatar>
        <Avatar muted>RV</Avatar>
        <Avatar size="lg">IK</Avatar>
      </Section>
      <Section title="Form">
        <div className="grid w-full gap-4 sm:grid-cols-3">
          <FormField label="Username" help="3–64 characters.">
            <Input defaultValue="imran.k" />
          </FormField>
          <FormField label="Password" error="Use at least 12 characters.">
            <Input type="password" defaultValue="short" />
          </FormField>
          <FormField label="Status">
            <Select>
              <option>All statuses</option>
              <option>Active</option>
            </Select>
          </FormField>
        </div>
        <label className="flex items-center gap-2 text-[13px]">
          <Checkbox defaultChecked /> Active
        </label>
        <div className="w-full max-w-[340px]">
          <OtpInput value={code} onChange={setCode} />
        </div>
      </Section>
      <Section title="Alerts">
        <div className="grid w-full gap-2">
          <Alert tone="danger">Incorrect username or password. Check both and try again.</Alert>
          <Alert tone="warn">If it's lost, rotate the secret to get a new one.</Alert>
          <Alert tone="info">Tokens for this application are refreshed within seconds.</Alert>
          <Alert tone="ok">Password changed.</Alert>
        </div>
      </Section>
      <Card>
        <CardHeader title="KeyCut" description="Hover or focus a tooth." />
        <CardBody>
          <KeyCut bits={BITS} meta="pm Hg · pv 7 · ver 4" />
        </CardBody>
      </Card>
      <Card>
        <Tabs defaultValue="a">
          <div className="px-[18px] pt-3">
            <TabsList>
              <TabsTrigger value="a" count={2}>
                Access
              </TabsTrigger>
              <TabsTrigger value="b" count={3}>
                Sessions
              </TabsTrigger>
              <TabsTrigger value="c">Profile</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="a">
            <DataTable
              rows={[
                { id: "1", name: "aditi.rao", app: "ANPR", status: "active" },
                { id: "2", name: "rahul.verma", app: "SNVR", status: "disabled" },
              ]}
              rowKey={(r) => r.id}
              columns={[
                { key: "n", header: "User", primary: true, cell: (r) => r.name },
                { key: "a", header: "App", cell: (r) => <Chip>{r.app}</Chip> },
                { key: "s", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
              ]}
            />
          </TabsContent>
          <TabsContent value="b">
            <DataTable
              rows={undefined}
              loading
              rowKey={() => ""}
              columns={[{ key: "x", header: "Loading", primary: true, cell: () => null }]}
            />
          </TabsContent>
          <TabsContent value="c">
            <EmptyState
              icon={ScrollText}
              title="Nothing yet"
              description="An empty screen is an invitation to act."
            />
          </TabsContent>
        </Tabs>
      </Card>
      <Section title="Dialog and skeleton">
        <Button variant="danger-ghost" onClick={() => setConfirm(true)}>
          <Trash2 />
          Open confirm dialog
        </Button>
        <Skeleton className="h-4 w-40" />
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          icon={<Trash2 />}
          title="Disable imran.k?"
          description="They are signed out everywhere at once. You can enable the account again later."
          confirmLabel="Disable user"
          onConfirm={() => setConfirm(false)}
        />
      </Section>
    </div>
  );
}
