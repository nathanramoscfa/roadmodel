// web/components/SoftSignupWall.tsx
"use client";

import Link from "next/link";
import { cloneElement, useState } from "react";
import type { ReactElement } from "react";

interface ComposerChildProps {
  onSubmit: (text: string) => boolean | void;
}

interface SoftSignupWallProps {
  children: ReactElement<ComposerChildProps>;
}

export function SoftSignupWall({ children }: SoftSignupWallProps) {
  const [showModal, setShowModal] = useState(false);

  function interceptSubmit(text: string): boolean {
    if (text.trim()) {
      setShowModal(true);
      return false;
    }
    return true;
  }

  return (
    <>
      {cloneElement(children, { onSubmit: interceptSubmit })}
      {showModal ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="presentation"
        >
          <button
            type="button"
            aria-label="Close dialog backdrop"
            className="absolute inset-0 bg-brand-slate-900/50"
            onClick={() => setShowModal(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="soft-signup-wall-title"
            className={
              "relative z-10 w-full max-w-md rounded-xl border " +
              "border-brand-slate-200 bg-white p-6 shadow-lg"
            }
          >
            <h2
              id="soft-signup-wall-title"
              className="text-lg font-semibold text-brand-slate-900"
            >
              Sign in required
            </h2>
            <p className="mt-3 text-sm text-brand-slate-600">
              Sign in to send your message. Your text stays right where
              you typed it.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className={
                  "rounded-lg border border-brand-slate-300 px-4 py-2 " +
                  "text-sm font-medium text-brand-slate-700 transition " +
                  "hover:bg-brand-slate-50"
                }
              >
                Cancel
              </button>
              <Link
                href="/login?next=/roadmap"
                className={
                  "rounded-lg bg-brand-accent px-4 py-2 text-sm " +
                  "font-semibold text-white shadow-sm transition " +
                  "hover:bg-brand-accent-hover"
                }
              >
                Sign in
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
