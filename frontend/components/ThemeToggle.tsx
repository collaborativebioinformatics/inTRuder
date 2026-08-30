"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

/**
 * Stamps `data-theme` on <html>. The CSS defines light on bare :root, dark under
 * both the OS media query and the explicit stamp, so the toggle wins either way
 * and "system" simply removes the stamp.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    try {
      const stored = localStorage.getItem("intruder-theme") as Theme | null;
      if (stored) setTheme(stored);
    } catch {
      // Private windows and blocked site data are fine — system default holds.
    }
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("intruder-theme", theme);
    } catch {
      // Non-fatal.
    }
  }, [theme]);

  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

  return (
    <button
      type="button"
      onClick={() => setTheme(next[theme])}
      title={`Theme: ${theme}. Click to switch.`}
      className="rounded-md border border-hairline px-2 py-1 text-[11px] text-ink-secondary transition-colors hover:border-baseline hover:text-ink"
    >
      {theme === "system" ? "auto" : theme}
    </button>
  );
}
