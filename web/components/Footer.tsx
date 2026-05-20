// web/components/Footer.tsx
import Link from "next/link";

const GITHUB_URL = "https://github.com/nathanramoscfa/roadmodel";
const ARCFORGE_URL = "https://arcforgelabs.io";

export function Footer() {
  return (
    <footer className="border-t border-brand-slate-200 bg-brand-slate-900 py-12 text-brand-slate-300">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 px-6 sm:flex-row sm:justify-between">
        <nav className="flex flex-wrap justify-center gap-6 text-sm">
          <Link
            href={GITHUB_URL}
            className="hover:text-white"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </Link>
          <Link href="/privacy" className="hover:text-white">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-white">
            Terms
          </Link>
        </nav>
        <p className="text-sm">
          © 2026{" "}
          <Link
            href={ARCFORGE_URL}
            className="hover:text-white"
            target="_blank"
            rel="noopener noreferrer"
          >
            Arcforge Digital Labs LLC
          </Link>
        </p>
      </div>
    </footer>
  );
}
