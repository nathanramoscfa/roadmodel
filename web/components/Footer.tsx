// web/components/Footer.tsx
import Link from "next/link";

const GITHUB_URL = "https://github.com/nathanramoscfa/roadmodel";
const ARCFORGE_URL = "https://arcforgelabs.io";

export function Footer() {
  return (
    <footer className="border-t border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-900 py-12 text-brand-slate-300">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 px-6 sm:flex-row sm:justify-between">
        <nav className="flex flex-wrap justify-center gap-6 text-sm max-md:gap-x-4 max-md:gap-y-0 [&>a]:max-md:flex [&>a]:max-md:min-h-11 [&>a]:max-md:min-w-11 [&>a]:max-md:items-center [&>a]:max-md:justify-center">
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
