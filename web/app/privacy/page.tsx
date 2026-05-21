// web/app/privacy/page.tsx
import Link from "next/link";
import { Footer } from "@/components/Footer";

export const metadata = {
  title: "Privacy — roadmodel",
  description: "What roadmodel.ai collects, why, and what it doesn't.",
};

const ARCFORGE_URL = "https://arcforgelabs.io";

export default function PrivacyPage() {
  return (
    <>
      <article className="mx-auto max-w-2xl px-6 py-16 sm:py-20">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 sm:text-4xl">
          Privacy
        </h1>
        <p className="mt-2 text-sm text-brand-slate-500">
          Last updated: 2026-05-20.
        </p>

        <div className="prose prose-slate mt-8 max-w-none text-brand-slate-700">
          <p>
            <strong>roadmodel.ai</strong> is an anonymous AI model-recommendation
            service operated by Arcforge Digital Labs LLC (&ldquo;we&rdquo;,
            &ldquo;us&rdquo;). This page describes what we collect and what we
            do not.
          </p>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            What we collect (and what we don&rsquo;t)
          </h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>
              Your task description is sent in real time to AI providers
              (currently Google Gemini 2.5 Flash, with Anthropic Haiku 4.5 as
              a fallback) to generate the recommendation.{" "}
              <strong>
                We do not store task descriptions or recommendation outputs
              </strong>{" "}
              in our database.
            </li>
            <li>
              We log one audit row per request containing: a salted hash of
              your IP, a salted hash of your user agent, the route name (e.g.
              <code className="px-1">/api/recommend</code>), the provider and
              model that served the request, token counts, the cost in USD,
              and the outcome (<code className="px-1">ok</code>,{" "}
              <code className="px-1">rate_limited</code>, etc.). The raw IP
              and user agent are never stored.
            </li>
            <li>
              No accounts, no email collection, and no cookies beyond what
              Next.js needs for the request lifecycle.
            </li>
          </ul>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            Why we collect it
          </h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>
              Rate limiting — at most 3 recommendations per day, with a
              10-per-minute burst cap, per salted IP+UA hash.
            </li>
            <li>
              Abuse prevention and aggregate usage analytics for capacity
              planning and cost ceilings.
            </li>
          </ul>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            Third parties
          </h2>
          <ul className="mt-3 list-disc space-y-2 pl-6">
            <li>Vercel — application hosting.</li>
            <li>Supabase — audit log storage.</li>
            <li>Upstash Redis — rate-limit counters.</li>
            <li>
              Anthropic and Google — AI inference. Each provider has its own
              privacy policy that governs how it processes prompts in transit.
            </li>
          </ul>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            Retention
          </h2>
          <p className="mt-3">
            Audit log rows are retained for operational and abuse-prevention
            purposes. The IP and user-agent hashing salt is rotated quarterly,
            severing correlation across rotation periods. We will publish a
            specific retention window here once it is enforced by automation.
          </p>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            Your rights
          </h2>
          <p className="mt-3">
            Because we do not store identifiers (only salted hashes), we
            cannot link an audit row back to you. If you have a privacy
            concern, contact us via{" "}
            <Link
              href={ARCFORGE_URL}
              className="text-brand-accent hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              arcforgelabs.io
            </Link>
            .
          </p>

          <h2 className="mt-8 text-xl font-semibold text-brand-slate-900">
            Changes
          </h2>
          <p className="mt-3">
            We will update the &ldquo;Last updated&rdquo; date above when this
            policy changes. Material changes will be noted in the project
            ROADMAP.
          </p>
        </div>
      </article>
      <Footer />
    </>
  );
}
