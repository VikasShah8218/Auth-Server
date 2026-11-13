import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { currentTheme, setTheme, type Theme } from "@/lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setThemeState] = useState<Theme>(() => currentTheme());

  // Follow the system while the person hasn't picked a theme.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setThemeState(currentTheme());
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const dark = theme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      className={className}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      onClick={() => {
        const next = dark ? "light" : "dark";
        setTheme(next);
        setThemeState(next);
      }}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}
