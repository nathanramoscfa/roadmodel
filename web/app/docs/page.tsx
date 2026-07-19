// web/app/docs/page.tsx
import { BenchmarkReference } from "@/components/BenchmarkReference";
import { RatingScale } from "@/components/RatingScale";

export const metadata = {
  title: "Docs — roadmodel",
  description:
    "How roadmodel recommends a model, the S→D rating scale, and the benchmarks it cites.",
};

export default function DocsPage() {
  return (
    <section className="mx-auto max-w-3xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 dark:text-brand-slate-50 sm:text-4xl">
          Documentation
        </h1>
        <p className="mt-3 text-brand-slate-600 dark:text-brand-slate-300">
          How roadmodel turns a prompt into a recommendation, the rating scale
          behind it, and the benchmarks it cites.
        </p>
      </header>

      <div className="mt-12 space-y-12">
        <section aria-labelledby="how-heading" className="scroll-mt-20">
          <h2
            id="how-heading"
            className="text-xl font-semibold tracking-tight text-brand-slate-900 dark:text-brand-slate-50"
          >
            How roadmodel works
          </h2>
          <div className="mt-2 space-y-3 text-brand-slate-600 dark:text-brand-slate-300">
            <p>
              Input your prompt and roadmodel recommends a <strong>model</strong>,
              the <strong>platform</strong> to run it on, the{" "}
              <strong>settings</strong> (reasoning effort, thinking, Max Mode), and an
              estimated{" "}
              <strong>cost</strong> &mdash; with a plain-English rationale. A{" "}
              <strong>backup</strong> model is named in case the top pick is
              unavailable to you.
            </p>
            <p>
              The pick is grounded in each model&rsquo;s <strong>per-category
              rating</strong> (below) and the public benchmarks those ratings
              synthesize. The selection algorithm reads your prompt&rsquo;s task
              category and complexity to set a minimum required rating, then picks the
              highest-rated available model that clears it &mdash; breaking ties by a
              secondary category and finally by cost.
            </p>
            <p>
              Recommendations are produced by a fast free-tier engine, or a
              higher-quality frontier engine for signed-in users. That engine is named
              under each result &mdash; it is what generated the analysis, not the
              recommended model itself.
            </p>
            <p>
              Two filters run before quality ever enters: a{" "}
              <strong>jurisdiction</strong> filter (drop providers outside your allowed
              regions) and an <strong>availability</strong> filter (never recommend a
              model whose provider has pulled or restricted access &mdash; checked
              automatically every day).
            </p>
          </div>
        </section>

        <section aria-labelledby="effort-heading" className="scroll-mt-20">
          <h2
            id="effort-heading"
            className="text-xl font-semibold tracking-tight text-brand-slate-900 dark:text-brand-slate-50"
          >
            Reasoning effort
          </h2>
          <div className="mt-2 space-y-3 text-brand-slate-600 dark:text-brand-slate-300">
            <p>
              How hard a model <em>thinks</em> is a separate dial from which model you
              pick. A bigger model and more reasoning effort are two different levers
              &mdash; and effort is only worth turning down when it actually costs you
              something: pay-per-token spend, a usage limit you can hit, or latency you
              care about.
            </p>
            <p>
              So roadmodel keeps effort high by default and lowers it only when doing so
              saves you real cost. Each of the three picks &mdash; Cost, Balanced,
              Quality &mdash; can therefore run at full effort while still differing by
              model, so the Cost pick is a <em>smaller</em> model thinking hard, not a
              hobbled one.
            </p>
            <p>
              You control this under <strong>Settings &rarr; Reasoning effort</strong>:
            </p>
            <ul className="ml-5 list-disc space-y-1">
              <li>
                <strong>Automatic</strong> &mdash; match effort to your plan. A top-tier
                subscription with headroom keeps effort maxed; a smaller plan scales it
                down to protect your usage budget.
              </li>
              <li>
                <strong>Always maximum effort</strong> &mdash; if you rarely or never hit
                your usage limits, keep reasoning maxed on every pick.
              </li>
              <li>
                <strong>Scale effort to save budget</strong> &mdash; dial reasoning down
                on the cheaper picks to conserve your usage.
              </li>
            </ul>
            <p>
              This changes only how much a pick reasons, never which model is chosen
              &mdash; and the named <strong>backup</strong> follows the same setting,
              shown with its own platform and effort.
            </p>
          </div>
        </section>

        <RatingScale id="ratings" />
        <BenchmarkReference id="benchmarks" />
      </div>
    </section>
  );
}
