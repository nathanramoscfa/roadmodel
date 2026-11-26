// web/lib/benchmark-grid.ts
//
// The UNIFORM benchmark layer for /models: column definitions over the
// Artificial Analysis dataset in data/benchmarks.json (built by
// update/fetch_aa_benchmarks.py). One lab, one methodology, one scale per
// column — so every number in a column is comparable with every other, and a
// blank means "AA has not measured this model on this test", never "we did
// not look". This is what replaced the per-row prose mining in
// lib/benchmark-scores.ts, which could only show whatever each row's cron
// text happened to cite, on whatever scale the citation used.
//
// PURE DATA — no JSON import here, so the client table can import it. The
// server page reads data/benchmarks.json, projects each model to a BenchRow
// with exactly the GRID_COLUMNS keys, and passes it down as props.

import type { Category, Rating } from "@/lib/catalog-fields";

// Keys as the AA Insights API names them (evaluations.<key>), plus the two
// performance fields promoted to columns.
export type BenchKey =
  | "artificial_analysis_intelligence_index"
  | "artificial_analysis_coding_index"
  | "hle"
  | "gpqa"
  | "scicode"
  | "terminalbench_v2_1"
  | "terminalbench_v4_0"
  | "tau_banking"
  | "ifbench"
  | "lcr"
  | "median_output_tokens_per_second";

export type BenchUnit = "index" | "fraction" | "tok/s";

export interface BenchColumn {
  key: BenchKey;
  // Column header (short) and the full benchmark name for the tooltip.
  short: string;
  label: string;
  definition: string;
  unit: BenchUnit;
  // Source leaderboard / methodology page for the tooltip link.
  url: string;
  // The rating category this figure is evidence for, if any. The ratings view
  // shows this column's value under that category's letter.
  category?: Category;
}

export const AA_HOME = "https://artificialanalysis.ai/";

// Display order for the "Benchmark scores" grid. Composites first, then the
// individual evaluations grouped roughly by what they measure, speed last.
export const GRID_COLUMNS: BenchColumn[] = [
  {
    key: "artificial_analysis_intelligence_index",
    short: "AA Index",
    label: "Artificial Analysis Intelligence Index",
    definition:
      "AA's composite over its evaluation suite — the one published overall number; 0–100. Scores are not comparable across index versions.",
    unit: "index",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index",
    category: "planning",
  },
  {
    key: "artificial_analysis_coding_index",
    short: "Coding Idx",
    label: "Artificial Analysis Coding Index",
    definition:
      "AA's composite of its coding evaluations (Terminal-Bench Hard and SciCode); 0–100, as AA published it before it moved to newer evaluation releases. The coding letter reads SciCode with the current Terminal-Bench release instead.",
    unit: "index",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-coding-index",
  },
  {
    key: "hle",
    short: "HLE",
    label: "Humanity's Last Exam",
    definition:
      "Frontier-difficulty exam across academic disciplines; percent correct as measured by AA. The hardest general-knowledge test in wide use.",
    unit: "fraction",
    url: "https://agi.safe.ai/",
    category: "knowledge",
  },
  {
    key: "gpqa",
    short: "GPQA",
    label: "GPQA Diamond",
    definition:
      "Graduate-level science questions written to be Google-proof; percent correct as measured by AA.",
    unit: "fraction",
    url: "https://github.com/idavidrein/gpqa",
  },
  {
    key: "scicode",
    short: "SciCode",
    label: "SciCode",
    definition:
      "Coding problems drawn from real scientific research workflows; percent of sub-problems solved, as measured by AA.",
    unit: "fraction",
    url: "https://scicode-bench.github.io/",
  },
  {
    key: "terminalbench_v2_1",
    short: "TB 2.1",
    label: "Terminal-Bench 2.1",
    definition:
      "The previous Terminal-Bench release: autonomous multi-step tasks in a real terminal; percent of tasks completed, as run by AA on models released before the current release took over.",
    unit: "fraction",
    url: "https://www.tbench.ai/",
  },
  {
    key: "terminalbench_v4_0",
    short: "TB 4.0",
    label: "Terminal-Bench 4.0",
    definition:
      "The agentic benchmark: the current Terminal-Bench release, harder autonomous multi-step tasks in a real terminal; percent of tasks completed, as run by AA. It is the Terminal-Bench release AA runs on newly released models.",
    unit: "fraction",
    url: "https://www.tbench.ai/",
    category: "agentic",
  },
  {
    key: "tau_banking",
    short: "τ² Bank",
    label: "τ²-bench (banking)",
    definition:
      "Tool-use with a simulated customer in the banking domain; pass^1 rate, as run by AA. A conversation-plus-tools agentic test, complementing Terminal-Bench's solo terminal tasks.",
    unit: "fraction",
    url: "https://github.com/sierra-research/tau2-bench",
  },
  {
    key: "ifbench",
    short: "IFBench",
    label: "IFBench",
    definition:
      "Precise instruction-following under unusual, verifiable constraints; percent of constraints satisfied, as measured by AA.",
    unit: "fraction",
    url: "https://github.com/allenai/IFBench",
  },
  {
    key: "lcr",
    short: "AA-LCR",
    label: "AA Long Context Reasoning",
    definition:
      "Reasoning over ~100k-token documents (multi-document question answering); percent correct, as measured by AA. The uniform long-context figure.",
    unit: "fraction",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning",
    category: "long-context",
  },
  {
    key: "median_output_tokens_per_second",
    short: "Speed",
    label: "Output speed (tokens/s)",
    definition:
      "Median output tokens per second on the provider's first-party API, as measured by AA. Blank where AA has not benchmarked the endpoint's throughput.",
    unit: "tok/s",
    url: "https://artificialanalysis.ai/",
    category: "speed",
  },
];

export const GRID_COLUMN_BY_KEY: Record<BenchKey, BenchColumn> = Object.fromEntries(
  GRID_COLUMNS.map((c) => [c.key, c]),
) as Record<BenchKey, BenchColumn>;

// Category → the uniform column that is evidence for that category's letter
// (named in the category header's tooltip). Planning reads the AA
// Intelligence Index: no benchmark tests planning alone, and the index is AA's
// composite of its whole suite. Multimodal has no evaluation in this dataset.
export const CATEGORY_FIGURE: Partial<Record<Category, BenchKey>> = Object.fromEntries(
  GRID_COLUMNS.filter((c) => c.category).map((c) => [c.category, c.key]),
);

// The five categories whose letter is DERIVED from its evidence column by
// update/derive_ratings.py for every model AA measures: by gap to the
// category leader, in points (S ≤ 5, A ≤ 20, B ≤ 35, C ≤ 50, else D), or,
// for a RANK_DERIVATION category, by rank.
// Speed has an evidence column for display but stays estimated: AA's tokens/s
// is measured on the provider's first-party endpoint, at the model's headline
// effort (its top measured one, update/fetch_aa_benchmarks.py).
export const DERIVED_CATEGORIES: ReadonlySet<Category> = new Set<Category>([
  "coding",
  "planning",
  "agentic",
  "long-context",
  "knowledge",
]);
export const DERIVATION_BANDS: readonly { max: number; letter: string }[] = [
  { max: 5, letter: "S" },
  { max: 20, letter: "A" },
  { max: 35, letter: "B" },
  { max: 50, letter: "C" },
];

// Categories lettered by RANK on their evidence instead of by gap: of every
// RANK_OUT_OF measured models, the first `count` of each letter in order, D
// for the rest. The top-ranked model is always the first letter, and a tie
// group shares its mean position, so it never splits. Agentic reads
// Terminal-Bench 4.0, whose leader sits far above the field, so the gap bands
// would have dropped most models (#789). Mirrors update/derive_ratings.py
// RANK_SHARES (tests/test_derived_ratings.py holds the two together).
export const RANK_OUT_OF = 40;
export type RankShares = readonly { letter: Rating; count: number }[];
export const RANK_DERIVATION: Partial<Record<Category, RankShares>> = {
  coding: [
    { letter: "S", count: 8 },
    { letter: "A", count: 19 },
    { letter: "B", count: 6 },
    { letter: "C", count: 2 },
  ],
  agentic: [
    { letter: "S", count: 9 },
    { letter: "A", count: 16 },
    { letter: "B", count: 7 },
    { letter: "C", count: 2 },
  ],
};

// Categories whose evidence is a COMPOSITE: the mean of the model's mid-rank
// percentiles (0–1) on each part, among the models measured on every part.
// Coding pairs SciCode with Terminal-Bench 4.0, the evaluations AA's own
// Coding Index averaged, on the releases AA runs today. Mirrors
// update/derive_ratings.py COMPOSITES.
export const COMPOSITE_DERIVATION: Partial<
  Record<Category, { label: string; parts: readonly BenchKey[] }>
> = {
  coding: { label: "SciCode + Terminal-Bench 4.0", parts: ["scicode", "terminalbench_v4_0"] },
};

// The highest letter an unmeasured model holds in a derived category when
// roadmodel's launch-table estimate does not place that category's benchmark
// (update/derive_ratings.py ESTIMATE_CEILING); an estimated letter can be S.
export const ESTIMATE_CEILING: Rating = "A";

// The evidence a derived category's letter reads, by name.
export function evidenceLabel(cat: Category): string | null {
  const composite = COMPOSITE_DERIVATION[cat];
  if (composite) return composite.label;
  const key = CATEGORY_FIGURE[cat];
  return key ? GRID_COLUMN_BY_KEY[key].label : null;
}

// {id → composite} for every row measured on all of `parts`, exactly as
// update/derive_ratings.py with_composites (a lone measured row scores 1).
export function compositeScores(
  rows: readonly { id: string; bench: BenchRow | null }[],
  parts: readonly BenchKey[],
): Map<string, number> {
  const measured = rows.flatMap((r) => {
    const values = parts.map((p) => r.bench?.values[p] ?? null);
    return values.every((v) => v !== null) ? [{ id: r.id, values: values as number[] }] : [];
  });
  const n = measured.length;
  const out = new Map<string, number>();
  for (const r of measured) {
    const pcts = r.values.map((v, i) => {
      if (n === 1) return 1;
      let below = 0;
      let tied = 0;
      for (const o of measured) {
        if (o.values[i] < v) below += 1;
        else if (o.values[i] === v) tied += 1;
      }
      return (below + (tied - 1) / 2) / (n - 1);
    });
    out.set(r.id, pcts.reduce((a, b) => a + b, 0) / pcts.length);
  }
  return out;
}

// The letter a value earns by rank among a column's measured values (sorted
// ascending), exactly as update/derive_ratings.py letter_for_rank: the centre
// of the tie group's mean slot, (position + ½) / n, against the cumulative
// shares, in integers (2·position + 1 = 2·better + tied).
export function rankLetter(value: number, sortedAsc: readonly number[], shares: RankShares): Rating {
  let better = 0;
  let tied = 0;
  for (const v of sortedAsc) {
    if (v > value) better += 1;
    else if (v === value) tied += 1;
  }
  if (better === 0) return shares[0].letter;
  const slot = 2 * better + tied;
  let cum = 0;
  for (const share of shares) {
    cum += share.count;
    if (slot * RANK_OUT_OF < 2 * sortedAsc.length * cum) return share.letter;
  }
  return "D";
}

// "of every 40 measured models, the top 9 are S, the next 16 A, 7 B, 2 C,
// the rest D" — the rank rule in words, from the constants.
export function rankRuleText(shares: RankShares): string {
  const [first, ...rest] = shares;
  const next = rest.map((s) => `${s.count} ${s.letter}`).join(", ");
  return `of every ${RANK_OUT_OF} measured models, the top ${first.count} are ${first.letter}, the next ${next}, the rest D`;
}

// Points on the derivation scale: indices as-is, fractions ×100.
export function benchPoints(value: number, unit: BenchUnit): number {
  return unit === "fraction" ? value * 100 : value;
}

// Within-column quintile band for a measured value: 5 = top 20% of measured
// models on that column … 1 = bottom 20%. Every grid column is higher-is-
// better on one scale, so the band is comparable across columns even though
// the units are not — that is what the cell colors encode. Ranks among
// MEASURED values only; a "—" has no band.
export type Band = 1 | 2 | 3 | 4 | 5;

export function bandFor(value: number | null, sortedMeasured: number[]): Band | null {
  if (value === null || sortedMeasured.length === 0) return null;
  // Share of measured values strictly below this one → quintile.
  let below = 0;
  while (below < sortedMeasured.length && sortedMeasured[below] < value) below += 1;
  const pct = below / sortedMeasured.length;
  return (Math.min(4, Math.floor(pct * 5)) + 1) as Band;
}

// Cost/quality Pareto frontier: a model is on it when NO other model is both
// cheaper and higher on the AA Intelligence Index. Zero tunable weights — the
// standard answer to "what is the best value" that a quality ÷ price ratio
// gets wrong (a ratio is dominated by the two-orders-of-magnitude price range
// and crowns the cheapest weak model). Ties on price resolve to the higher
// index; ties on index to the cheaper price. The page passes the blended
// price, the same one the Score and the charts use.
export function paretoFrontier<T extends { price: number; index: number | null }>(
  rows: readonly T[],
): Set<T> {
  const measured = rows.filter((r): r is T & { index: number } => r.index !== null);
  const sorted = [...measured].sort((a, b) => a.price - b.price || b.index - a.index);
  const frontier = new Set<T>();
  let best = Number.NEGATIVE_INFINITY;
  for (const r of sorted) {
    if (r.index > best) {
      frontier.add(r);
      best = r.index;
    }
  }
  return frontier;
}

// The frontier, read per model: for every measured row, the highest AA Index
// on sale at that row's price or less, across the WHOLE catalog (a tie on
// index goes to the cheaper model). A row that is its own leader is on the
// frontier, the same set paretoFrontier returns; any other row is beaten
// outright by its leader, which costs no more and scores higher. Whereas the
// Score measures vertical distance from the market's continuous price line,
// the frontier marks every non-dominated model outright.
export function frontierLeaders<T extends { price: number; index: number | null }>(
  rows: readonly T[],
): Map<T, T> {
  const measured = rows.filter((r): r is T & { index: number } => r.index !== null);
  const sorted = [...measured].sort((a, b) => a.price - b.price || b.index - a.index);
  const leaders = new Map<T, T>();
  let best: (T & { index: number }) | null = null;
  for (const r of sorted) {
    if (best === null || r.index > best.index) best = r;
    leaders.set(r, best);
  }
  return leaders;
}

// Quality bands for the table's "group by quality" view: the AA Intelligence
// Index in fixed ten-point bands (50–59.9, 40–49.9, …), labelled by their
// literal range, so a band means exactly what it says. Fixed rather than
// relative to the leader, so a model changes band only when its own index
// moves (or AA re-versions the index, which moves every model at once). The
// bands come from the models, not a list: the first model past 60 opens a
// "60–69.9" group on its own. The index tops out at 100, which joins the
// 90s band ("90–100") rather than opening a band of one value. An unmeasured
// model has no band.
export const QUALITY_BAND_WIDTH = 10;
const QUALITY_TOP_BAND = 100 - QUALITY_BAND_WIDTH;

export function qualityBand(index: number | null): number | null {
  if (index === null || !Number.isFinite(index)) return null;
  return Math.min(QUALITY_TOP_BAND, Math.floor(index / QUALITY_BAND_WIDTH) * QUALITY_BAND_WIDTH);
}

// "40–49.9" (the AA Index is published to one decimal); the top band, which
// also holds 100, reads "90–100".
export function formatQualityBand(lo: number): string {
  if (lo >= QUALITY_TOP_BAND) return `${lo}–100`;
  return `${lo}–${(lo + QUALITY_BAND_WIDTH - 0.1).toFixed(1)}`;
}

// Price-adjusted Value (0–100% market percentile) over a Huber-robust,
// vintage-controlled market line with heteroskedastic local spread.
//
// Why this model over plain 1D OLS:
//   1. Vintage confounding (Simpson's Paradox): old cheap/open-weight models
//      linger in the catalog while old expensive flagships retire quickly.
//      Plain OLS over the pooled catalog tilts the price slope nearly 2× too
//      steeply (~15 vs ~8.4 AA pts/decade), over-rewarding cheap models and
//      penalising current mid/high-tier leaders. Fitting AA ~ log10(price) +
//      age_months with Huber IRLS isolates the true current-generation slope,
//      then anchors the baseline line at the current generation's vintage
//      (25th-percentile age behind the newest measured release — wall-clock
//      independent and deterministic). Every model, old or new, is judged
//      against today's line rather than given a vintage handicap.
//   2. Heteroskedasticity: residual dispersion narrows ~4× from low prices to
//      expensive flagships. A smooth price-varying scale
//      sigma(x) = sqrt(max(0, g0 + g1·x)^2 + measFloor^2) (with a 3-point AA
//      measurement-noise floor) replaces the flat global ±σ tie band so high-
//      price models aren't judged against low-price scatter and tiny 1–2 pt
//      benchmark jitters never blow up at the top end.
//   3. Intuitive 0–100% Value scale: standardised residuals
//      z = (index − expected(p)) / sigma(p) pass through the closed-form
//      Student-t (df = 5) CDF so 50% sits right on today's market line,
//      ≥ 75% marks standout value, and ≤ 25% marks poor value — scale-invariant
//      across AA index revisions and heavier-tailed than Normal so legacy
//      models remain distinguishable near the bottom.
export const VALUE_HIGH = 75;
export const VALUE_LOW = 25;
export const VALUE_MEAS_FLOOR = 3;
export const VALUE_T_DF = 5;

const HUBER_K = 1.345;
const MAD_TO_SIGMA = 0.6744897501960817;
const ABS_TO_SIGMA = Math.sqrt(Math.PI / 2);
const DAYS_PER_MONTH = 30.4375;

export interface ScoreFit {
  n: number;
  // Expected AA Index at $1/1M effort-adjusted price on today's market line.
  intercept: number;
  // AA Index points per decade (10×) of effort-adjusted price.
  slope: number;
  // AA Index points per month of model age (negative: newer models score higher).
  ageSlope: number;
  // Current-generation anchor age (months behind newest measured release_date).
  refAgeMonths: number;
  // True when release dates were available to control for vintage.
  vintageAdjusted: boolean;
  // Expected AA Index on today's line at the geometric-mean price (10^meanLogPrice).
  meanIndex: number;
  // Mean of log10(effort-adjusted blended price) over the n fitted models.
  meanLogPrice: number;
  minPrice: number;
  maxPrice: number;
  r2: number;
  // Representative local total σ at the geometric-mean price (in AA points).
  sigma: number;
  // Linear heteroskedastic market-spread fit: marketSigma(x) = max(0, sigmaIntercept + sigmaSlope * x).
  sigmaIntercept: number;
  sigmaSlope: number;
  // Irreducible AA benchmark measurement-noise floor (in AA points).
  measFloor: number;
  // Local total σ range across [minPrice, maxPrice].
  sigmaMin: number;
  sigmaMax: number;
  // Student-t degrees of freedom for the 0–100% Value percentile mapping.
  df: number;
}

export function blendedPrice(inputPer1m: number, outputPer1m: number): number {
  return (3 * inputPer1m + outputPer1m) / 4;
}

function median(vals: readonly number[]): number {
  const s = [...vals].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function quantile(vals: readonly number[], q: number): number {
  const s = [...vals].sort((a, b) => a - b);
  if (s.length === 1) return s[0];
  const pos = q * (s.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

function parseIsoDay(raw: string | null | undefined): number | null {
  if (!raw) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw.trim());
  if (!m) return null;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isFinite(ms) ? ms / 86_400_000 : null;
}

// Weighted least squares via Gaussian elimination with partial pivoting (p ≤ 3).
function solveWls(X: readonly (readonly number[])[], y: readonly number[], w: readonly number[]): number[] | null {
  const n = X.length;
  const p = X[0].length;
  const A: number[][] = Array.from({ length: p }, () => new Array<number>(p + 1).fill(0));
  for (let i = 0; i < n; i += 1) {
    const wi = w[i];
    const row = X[i];
    for (let a = 0; a < p; a += 1) {
      const wa = wi * row[a];
      for (let b = 0; b < p; b += 1) A[a][b] += wa * row[b];
      A[a][p] += wa * y[i];
    }
  }
  for (let col = 0; col < p; col += 1) {
    let piv = col;
    for (let r = col + 1; r < p; r += 1) {
      if (Math.abs(A[r][col]) > Math.abs(A[piv][col])) piv = r;
    }
    if (Math.abs(A[piv][col]) < 1e-12) return null;
    if (piv !== col) [A[col], A[piv]] = [A[piv], A[col]];
    const diag = A[col][col];
    for (let c = col; c <= p; c += 1) A[col][c] /= diag;
    for (let r = 0; r < p; r += 1) {
      if (r === col) continue;
      const factor = A[r][col];
      for (let c = col; c <= p; c += 1) A[r][c] -= factor * A[col][c];
    }
  }
  return A.map((row) => row[p]);
}

function huberIrls(X: readonly (readonly number[])[], y: readonly number[], maxIter = 40): number[] | null {
  const n = X.length;
  let beta = solveWls(X, y, new Array<number>(n).fill(1));
  if (!beta) return null;
  for (let iter = 0; iter < maxIter; iter += 1) {
    const res = y.map((yi, i) => yi - X[i].reduce((acc, v, j) => acc + v * beta![j], 0));
    const med = median(res);
    const mad = median(res.map((v) => Math.abs(v - med))) / MAD_TO_SIGMA;
    if (mad < 1e-6) break;
    const c = HUBER_K * mad;
    const w = res.map((v) => {
      const av = Math.abs(v);
      return av <= c ? 1 : c / av;
    });
    const next = solveWls(X, y, w);
    if (!next) break;
    const diff = Math.max(...next.map((v, j) => Math.abs(v - beta![j])));
    beta = next;
    if (diff < 1e-9) break;
  }
  return beta;
}

// Exact closed-form Student-t CDF for df = 5.
export function studentT5Cdf(t: number): number {
  const u = t / Math.sqrt(VALUE_T_DF);
  const d = 1 + u * u;
  const v = 0.5 + (1 / Math.PI) * (Math.atan(u) + u / d + (2 / 3) * (u / (d * d)));
  return Math.min(1, Math.max(0, v));
}

export function fitScoreModel(
  rows: readonly { price: number; index: number | null; releaseDate?: string | null }[],
): ScoreFit | null {
  const pts = rows.filter(
    (r): r is { price: number; index: number; releaseDate?: string | null } =>
      r.index !== null && Number.isFinite(r.index) && r.price > 0,
  );
  const n = pts.length;
  if (n < 3) return null;
  const xs = pts.map((p) => Math.log10(p.price));
  const ys = pts.map((p) => p.index);
  const meanLogPrice = xs.reduce((a, b) => a + b, 0) / n;
  const rawMeanIndex = ys.reduce((a, b) => a + b, 0) / n;
  let sxx = 0;
  let ssTot = 0;
  for (let i = 0; i < n; i += 1) {
    sxx += (xs[i] - meanLogPrice) ** 2;
    ssTot += (ys[i] - rawMeanIndex) ** 2;
  }
  if (sxx === 0 || ssTot === 0) return null;

  const parsedDays = pts.map((p) => parseIsoDay(p.releaseDate));
  const datedDays = parsedDays.filter((d): d is number => d !== null);
  const hasVintage =
    datedDays.length >= 4 && Math.max(...datedDays) - Math.min(...datedDays) > 0;

  let intercept: number;
  let slope: number;
  let ageSlope = 0;
  let refAgeMonths = 0;
  let vintageAdjusted = false;
  let residuals: number[];

  if (hasVintage) {
    const anchorDay = Math.max(...datedDays);
    const datedAges = datedDays.map((d) => (anchorDay - d) / DAYS_PER_MONTH);
    const medAge = median(datedAges);
    const ages = parsedDays.map((d) => (d === null ? medAge : (anchorDay - d) / DAYS_PER_MONTH));
    const X3 = xs.map((x, i) => [1, x, ages[i]]);
    const beta = huberIrls(X3, ys, 40);
    if (!beta) return null;
    refAgeMonths = quantile(datedAges, 0.25);
    intercept = beta[0] + beta[2] * refAgeMonths;
    slope = beta[1];
    ageSlope = beta[2];
    vintageAdjusted = true;
    residuals = ys.map((y, i) => y - (beta[0] + beta[1] * xs[i] + beta[2] * ages[i]));
  } else {
    const X2 = xs.map((x) => [1, x]);
    const beta = huberIrls(X2, ys, 40);
    if (!beta) return null;
    intercept = beta[0];
    slope = beta[1];
    residuals = ys.map((y, i) => y - (beta[0] + beta[1] * xs[i]));
  }

  const ssRes = residuals.reduce((acc, r) => acc + r * r, 0);
  const r2 = Math.max(0, 1 - ssRes / ssTot);

  // Price-varying market spread (Huber-robust on |r|·sqrt(pi/2)), combined with
  // the irreducible AA measurement-noise floor in quadrature.
  let sigmaIntercept: number;
  let sigmaSlope = 0;
  if (n >= 6) {
    const targets = residuals.map((r) => Math.abs(r) * ABS_TO_SIGMA);
    const g = huberIrls(
      xs.map((x) => [1, x]),
      targets,
      30,
    );
    if (g) {
      sigmaIntercept = g[0];
      sigmaSlope = g[1];
    } else {
      const medR = median(residuals);
      sigmaIntercept = median(residuals.map((r) => Math.abs(r - medR))) / MAD_TO_SIGMA;
    }
  } else {
    const medR = median(residuals);
    sigmaIntercept = median(residuals.map((r) => Math.abs(r - medR))) / MAD_TO_SIGMA;
  }

  const measFloor = VALUE_MEAS_FLOOR;
  const localSigma = (lx: number) => {
    const mkt = Math.max(0, sigmaIntercept + sigmaSlope * lx);
    return Math.sqrt(mkt * mkt + measFloor * measFloor);
  };
  const minPrice = Math.min(...pts.map((p) => p.price));
  const maxPrice = Math.max(...pts.map((p) => p.price));
  const sLo = localSigma(Math.log10(minPrice));
  const sHi = localSigma(Math.log10(maxPrice));

  return {
    n,
    intercept,
    slope,
    ageSlope,
    refAgeMonths,
    vintageAdjusted,
    meanIndex: intercept + slope * meanLogPrice,
    meanLogPrice,
    minPrice,
    maxPrice,
    r2,
    sigma: localSigma(meanLogPrice),
    sigmaIntercept,
    sigmaSlope,
    measFloor,
    sigmaMin: Math.min(sLo, sHi),
    sigmaMax: Math.max(sLo, sHi),
    df: VALUE_T_DF,
  };
}

// The expected index today's continuous market line gives at a blended price.
export function expectedIndex(fit: ScoreFit, price: number): number | null {
  if (!(price > 0)) return null;
  return fit.intercept + fit.slope * Math.log10(price);
}

// Local total standard deviation (±σ, in AA Index points) at a blended price:
// market spread at this price combined in quadrature with AA's noise floor.
export function sigmaAt(fit: ScoreFit, price: number): number | null {
  if (!(price > 0)) return null;
  const mkt = Math.max(0, fit.sigmaIntercept + fit.sigmaSlope * Math.log10(price));
  return Math.sqrt(mkt * mkt + fit.measFloor * fit.measFloor);
}

// Value percentile (0–100) for one model, or null when unmeasured / fit failed.
export function scoreFor(
  fit: ScoreFit | null,
  price: number,
  index: number | null,
): number | null {
  if (!fit || index === null || !(price > 0)) return null;
  const expected = expectedIndex(fit, price);
  const sigma = sigmaAt(fit, price);
  if (expected === null || sigma === null || !(sigma > 0)) return null;
  return studentT5Cdf((index - expected) / sigma) * 100;
}

// "89%" / "50%" / "0%" — integer market percentile, or "—" when unmeasured.
export function formatScore(score: number | null): string {
  if (score === null || !Number.isFinite(score)) return "—";
  const rounded = Math.min(100, Math.max(0, Math.round(score)));
  return `${rounded}%`;
}

// "+7.1" / "−3.2" / "0.0" — signed one-decimal AA points or z-score.
export function formatSigned(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "0.0";
  return (rounded > 0 ? "+" : "−") + Math.abs(rounded).toFixed(1);
}

// A model's Value breakdown: actual AA Index vs today's market line at its
// effort-adjusted price, divided by the local heteroskedastic spread σ(p), and
// mapped through the Student-t(5) CDF to a 0–100% market percentile.
export interface ScoreBreakdown {
  score: number; // 0–100 Value percentile
  index: number;
  expected: number;
  gap: number; // index − expected, in AA Index points
  sigma: number; // local ±σ(price), in AA Index points
  z: number; // gap ÷ sigma
  marketMean: number;
  price: number;
  typicalPrice: number;
  priceRatio: number;
  slope: number;
  ageSlope: number;
  refAgeMonths: number;
  vintageAdjusted: boolean;
  marketN: number;
  // One-decimal parts that add up exactly in whole tenths:
  //   gap             = index − expected
  //   expected        = marketMean − priceAdjustment
  //   value           = Math.round(score) (exact % printed in the table)
  shown: {
    index: number;
    expected: number;
    gap: number;
    sigma: number;
    z: number;
    marketMean: number;
    priceAdjustment: number;
    value: number;
  };
}

const tenths = (v: number) => Math.round(v * 10);

export function scoreBreakdown(
  fit: ScoreFit | null,
  price: number,
  index: number | null,
): ScoreBreakdown | null {
  if (!fit || index === null || !(price > 0)) return null;
  const expected = expectedIndex(fit, price);
  const sigma = sigmaAt(fit, price);
  if (expected === null || sigma === null || !(sigma > 0)) return null;
  const gap = index - expected;
  const z = gap / sigma;
  const score = studentT5Cdf(z) * 100;
  const typicalPrice = 10 ** fit.meanLogPrice;
  const iT = tenths(index);
  const eT = tenths(expected);
  const mT = tenths(fit.meanIndex);
  const gT = iT - eT;
  return {
    score,
    index,
    expected,
    gap,
    sigma,
    z,
    marketMean: fit.meanIndex,
    price,
    typicalPrice,
    priceRatio: price / typicalPrice,
    slope: fit.slope,
    ageSlope: fit.ageSlope,
    refAgeMonths: fit.refAgeMonths,
    vintageAdjusted: fit.vintageAdjusted,
    marketN: fit.n,
    shown: {
      index: iT / 10,
      expected: eT / 10,
      gap: gT / 10,
      sigma: tenths(sigma) / 10,
      z: tenths(z) / 10,
      marketMean: mT / 10,
      priceAdjustment: (mT - eT) / 10,
      value: Math.min(100, Math.max(0, Math.round(score))),
    },
  };
}

// Candidate tick values for a log10 price axis between two prices, coarsest
// series first: 1-2-5 when that already gives four ticks, else a finer
// "round price" series (so a tier spanning $9–$24 reads $10 $12 $15 $20
// rather than one lonely $10). The chart thins them further so no two labels
// touch at the width it is drawn.
export function priceTicks(lo: number, hi: number): number[] {
  const series = (steps: number[]) => {
    const ticks: number[] = [];
    for (let e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)) + 1; e += 1) {
      for (const s of steps) {
        const v = s * 10 ** e;
        if (v >= lo * 0.999 && v <= hi * 1.001) ticks.push(Number(v.toPrecision(6)));
      }
    }
    return ticks;
  };
  const coarse = series([1, 2, 5]);
  if (coarse.length >= 4) return coarse;
  return series([1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9]);
}

// "$0.13", "$1.25", "$10", "$19.95" — a price as an axis or card reads it.
export function formatUsd(v: number): string {
  if (v >= 100) return `$${Math.round(v)}`;
  if (Number.isInteger(v)) return `$${v}`;
  return `$${v.toFixed(2)}`;
}

// What the page carries per model: just the column values (null = not
// measured) plus the AA identity for the tooltip/attribution.
export interface BenchRow {
  aa_slug: string;
  aa_name: string;
  // AA's release date for the model ("2026-09-28"), or null when AA has none.
  release_date: string | null;
  values: Record<BenchKey, number | null>;
}

export function formatBench(value: number | null, unit: BenchUnit): string {
  if (value === null || Number.isNaN(value)) return "—";
  switch (unit) {
    case "fraction":
      return `${(value * 100).toFixed(1)}%`;
    case "tok/s":
      return `${Math.round(value)}`;
    default:
      return value.toFixed(1);
  }
}

// Numeric value for sorting; missing sorts last in either direction.
export function benchSortValue(row: BenchRow | null, key: BenchKey): number | null {
  const v = row?.values[key];
  return v === undefined ? null : v;
}

// Where a value stands among a column's measured values (sorted ascending):
// its rank from the top (1 = highest; tied values share the better rank), the
// number of measured models, and its mid-rank percentile, 0–100.
export interface Standing {
  rank: number;
  of: number;
  pct: number;
}

export function standing(value: number, sortedAsc: readonly number[]): Standing {
  let below = 0;
  let equal = 0;
  for (const v of sortedAsc) {
    if (v < value) below += 1;
    else if (v === value) equal += 1;
  }
  const of = sortedAsc.length;
  return {
    rank: of - below - equal + 1,
    of,
    pct: of === 0 ? 0 : (100 * (below + equal / 2)) / of,
  };
}

// The AA Index card's evidence: every evaluation column the model is measured
// on (the index and speed aside), with its standing in the catalog, and a
// verdict on whether the index rank agrees with them. The index is AA's
// composite of its evaluations, so a model's own benchmarks bear it out: its
// index percentile sits within EVIDENCE_TOLERANCE points of the median
// percentile of its benchmarks. Past that, the verdict says which way the
// index leans. Two benchmarks at least make a verdict.
export const EVIDENCE_TOLERANCE = 20;
export const EVIDENCE_MIN_BENCHMARKS = 2;

export type EvidenceVerdict = "agrees" | "above" | "below";

export interface EvidenceItem extends Standing {
  key: BenchKey;
  value: number;
}

export interface IndexEvidence {
  index: EvidenceItem;
  // Best standing first.
  items: EvidenceItem[];
  medianPct: number | null;
  verdict: EvidenceVerdict | null;
}

const INDEX_KEY: BenchKey = "artificial_analysis_intelligence_index";

export function indexEvidence(
  bench: BenchRow | null,
  columnValues: Readonly<Record<BenchKey, readonly number[]>>,
): IndexEvidence | null {
  const value = bench?.values[INDEX_KEY] ?? null;
  if (bench === null || value === null) return null;
  const at = (key: BenchKey, v: number): EvidenceItem => ({
    key,
    value: v,
    ...standing(v, columnValues[key] ?? []),
  });
  const items = GRID_COLUMNS.filter((c) => c.key !== INDEX_KEY && c.unit !== "tok/s")
    .flatMap((c) => {
      const v = bench.values[c.key];
      return v === null || v === undefined ? [] : [at(c.key, v)];
    })
    .sort((a, b) => b.pct - a.pct);
  const index = at(INDEX_KEY, value);
  if (items.length < EVIDENCE_MIN_BENCHMARKS) {
    return { index, items, medianPct: null, verdict: null };
  }
  const pcts = items.map((i) => i.pct).sort((a, b) => a - b);
  const mid = Math.floor(pcts.length / 2);
  const medianPct = pcts.length % 2 === 1 ? pcts[mid] : (pcts[mid - 1] + pcts[mid]) / 2;
  const lean = index.pct - medianPct;
  const verdict: EvidenceVerdict =
    lean > EVIDENCE_TOLERANCE ? "above" : lean < -EVIDENCE_TOLERANCE ? "below" : "agrees";
  return { index, items, medianPct, verdict };
}

// A model is NEW for its first NEW_RELEASE_DAYS days after its release date
// (AA's `release_date`; before AA lists it, the day it joined the catalog):
// its figures are launch-window results. Returns the day the tag clears
// ("2026-10-12") while `now` is before it, else null.
export const NEW_RELEASE_DAYS = 14;

export function newUntil(releaseDate: string | null | undefined, now: Date): string | null {
  if (!releaseDate || !/^\d{4}-\d{2}-\d{2}$/.test(releaseDate)) return null;
  const released = Date.parse(`${releaseDate}T00:00:00Z`);
  if (Number.isNaN(released)) return null;
  const until = released + NEW_RELEASE_DAYS * 86_400_000;
  return now.getTime() < until ? new Date(until).toISOString().slice(0, 10) : null;
}
