import { KeyRound } from "lucide-react";
import { useState } from "react";

import { CopyButton } from "@/components/common/CopyButton";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/input";

/** Shows a client secret once. It can't be closed by accident before the admin confirms they saved it. */
export function SecretDialog({
  clientId,
  secret,
  onClose,
}: {
  clientId: string;
  secret: string | null;
  onClose: () => void;
}) {
  const [saved, setSaved] = useState(false);

  return (
    <Dialog open={secret !== null} onOpenChange={(open) => !open && saved && onClose()}>
      <DialogContent
        onEscapeKeyDown={(event) => !saved && event.preventDefault()}
        onPointerDownOutside={(event) => event.preventDefault()}
      >
        <DialogBody
          icon={<KeyRound />}
          tone="accent"
          title={`Secret for ${clientId}`}
          description="Copy it into the server's secret store now. It is shown only this once and can't be read back later."
        >
          <div className="flex items-center gap-2 rounded-control border border-line bg-surface-2 py-1.5 pr-1.5 pl-3">
            <code className="min-w-0 flex-1 font-mono text-[13px] break-all">{secret}</code>
            <CopyButton value={secret ?? ""} label="Copy secret" />
          </div>
          <Alert tone="warn">
            If it's lost, rotate the secret to get a new one. The old one stops working at once.
          </Alert>
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg-2">
            <Checkbox checked={saved} onChange={(event) => setSaved(event.target.checked)} />
            I've saved the secret somewhere safe
          </label>
        </DialogBody>
        <DialogFooter>
          <Button
            variant="primary"
            disabled={!saved}
            onClick={() => {
              setSaved(false);
              onClose();
            }}
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
