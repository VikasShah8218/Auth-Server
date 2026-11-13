import { Link } from "@tanstack/react-router";
import { Compass } from "lucide-react";

import { EmptyState } from "@/components/common/States";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <EmptyState
        icon={Compass}
        title="This page doesn't exist"
        description="The link may be old, or the item was removed."
        action={
          <Button asChild variant="primary" size="sm">
            <Link to="/">Go to the dashboard</Link>
          </Button>
        }
      />
    </div>
  );
}
