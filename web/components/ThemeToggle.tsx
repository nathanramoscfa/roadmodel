// web/components/ThemeToggle.tsx
"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

// Light/dark theme toggle (T4). Flips the `dark` class on <html> and persists
// the choice to localStorage; the no-flash script in layout.tsx re-applies it
// before paint on the next load. Dark is the default — a user only gets light
// by explicitly toggling. Initial state is read from the live class, so it
// tracks whatever the no-flash script already applied.
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  // Sync initial state from the class the no-flash script already applied.
  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      // localStorage unavailable (private mode / SSR) — the toggle still works
      // for the current session; it just won't persist.
    }
    setDark(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      aria-pressed={dark}
      className={
        "rounded-md p-2 text-brand-slate-600 " +
        "hover:bg-brand-slate-50 hover:text-brand-slate-900 " +
        "dark:text-brand-slate-300 dark:hover:bg-brand-slate-800 dark:hover:text-brand-slate-50"
      }
    >
      {dark ? (
        <Sun className="h-5 w-5" aria-hidden="true" />
      ) : (
        <Moon className="h-5 w-5" aria-hidden="true" />
      )}
    </button>
  );
}
