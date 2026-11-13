import { Link } from "@tanstack/react-router";
import { ChevronDown, LogOut, ShieldCheck, User } from "lucide-react";

import { useLogout, useSession } from "@/api/session";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuHeader,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { fullName, userInitials } from "@/lib/format";

export function UserMenu() {
  const session = useSession();
  const logout = useLogout();
  const { user } = session;
  const name = fullName(user) || user.username;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-1.5 pr-1.5 pl-1" aria-label="Account menu">
          <Avatar size="sm">{userInitials(user)}</Avatar>
          <ChevronDown className="text-muted" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuHeader title={name} subtitle={`${user.username}${session.is_admin ? " · Admin" : ""}`} />
        <DropdownMenuItem asChild>
          <Link to="/account">
            <User />
            My account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/account" search={{ tab: "security" }}>
            <ShieldCheck />
            Security and MFA
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem tone="danger" onSelect={() => logout.mutate()} disabled={logout.isPending}>
          <LogOut />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
