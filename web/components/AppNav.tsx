// web/components/AppNav.tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Global navigation for the signed-in app surfaces (issue #153). Before
// this, every authed page (/recommend, /roadmap, /history, /settings) was a
// navigational dead-end — no link home or between surfaces. Rendered once in
// the root layout; it hides itself on marketing/auth chrome (home, login,
// onboarding, gate, privacy, terms) via usePathname, so those routes stay
// static and keep their own headers.
const NAV_LINKS: { href: string; label: string }[] = [
  { href: "/recommend", label: "Recommend" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

// Route prefixes the app nav appears on. Everything else (/, /login,
// /onboarding, /callback, /gate, /signout, /privacy, /terms) renders without it.
const APP_PREFIXES = ["/recommend", "/roadmap", "/history", "/settings"];

export function AppNav({ roadmapEnabled }: { roadmapEnabled: boolean }) {
  const pathname = usePathname();
  const onAppSurface = APP_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
  if (!onAppSurface) {
    return null;
  }

  // Recommender-only mode (issue #171): hide the Roadmap + History
  // links when the roadmap builder is disabled. Recommend + Settings
  // always render. The /roadmap + /history routes also redirect to
  // /recommend server-side, so this just keeps the nav consistent.
  const links = roadmapEnabled
    ? NAV_LINKS
    : NAV_LINKS.filter(
        (link) => link.href !== "/roadmap" && link.href !== "/history",
      );

  return (
    <nav
      aria-label="Primary"
      className="border-b border-brand-slate-200 bg-white"
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
        <Link
          href="/"
          className="text-sm font-semibold uppercase tracking-wide text-brand-accent"
        >
          roadmodel
        </Link>
        <div className="flex items-center gap-1 sm:gap-2">
          {links.map((link) => {
            const active =
              pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
                  (active
                    ? "bg-brand-slate-100 text-brand-slate-900"
                    : "text-brand-slate-600 hover:bg-brand-slate-50 hover:text-brand-slate-900")
                }
              >
                {link.label}
              </Link>
            );
          })}
          <form action="/signout" method="post" className="ml-1">
            <button
              type="submit"
              className="rounded-md px-3 py-1.5 text-sm font-medium text-brand-slate-600 hover:bg-brand-slate-50 hover:text-brand-slate-900"
            >
              Sign out
            </button>
          </form>
        </div>
      </div>
    </nav>
  );
}
