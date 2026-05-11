# roadmodel — Pro-Forma Financial Model

> **Status:** Draft v1 — illustrative, not predictive
> **Owner:** Nathan Ramos
> **Companion to:** [ROADMAP.md](ROADMAP.md) §6 Monetization
> Strategy
> **Horizon:** 12 months from Phase 4 launch (month 0)
> **Last updated:** May 2026

This is a pro-forma — a model of how revenue and cost would
develop under stated assumptions, **not a forecast**. Every
number traces to an explicit assumption in §3. Change the
assumption and the table changes.

The horizon is 12 months from the Phase 4 launch (the first
public URL). Validation gates A and B in
[ROADMAP.md](ROADMAP.md) §4 determine whether Phases 5 and 6
ship at all; the model treats those gates as conditional
milestones, not certainties.

---

## 1. Revenue drivers

Six drivers compose monthly Pro revenue. The model is
intentionally flat — no viral coefficient, no SEO compounding,
no enterprise windfall. Add those if you want; mark them clearly
as scenario overrides.

| Driver        | Sym | Definition                                    |
|---------------|-----|-----------------------------------------------|
| Visitors       | V   | Unique browser sessions per month             |
| Free signup    | s   | Fraction of visitors creating a free account  |
| Cap-hit rate   | h   | Fraction of free MAUs hitting 3-roadmap cap   |
| Free→Pro       | c   | Fraction of cap-hitters who upgrade           |
| Pro churn      | k   | Fraction of Pro users canceling per month     |
| Pro price      | P   | $15 launch; $19 ceiling                       |

Per-month formulas (let `F(t)` = cumulative free users at
month `t`):

```
new_free_signups(t) = V(t) × s
F(t)                = F(t−1) + new_free_signups(t)
cap_hits(t)         = F(t) × h
new_pro(t)          = cap_hits(t) × c
pro_count(t)        = pro_count(t−1) × (1 − k) + new_pro(t)
MRR(t)              = pro_count(t) × P
```

Free-user attrition is held at 0% to keep formulas simple. In
practice 5–10%/month free churn is realistic and would compress
`F(t)` by ~20–30% over 12 months — apply a haircut if you want
a tighter projection.

---

## 2. Cost drivers

| Cost item                             | Type     | Estimate per unit  |
|---------------------------------------|----------|--------------------|
| Backend PaaS                           | Fixed    | $5–15 / month      |
| Postgres                               | Fixed    | $0–10 / month      |
| Domain + Cloudflare                    | Fixed    | ~$1 / month        |
| Anthropic — single-prompt classify     | Variable | ~$0.001 / request  |
| Anthropic — annotate-only roadmap      | Variable | ~$0.10 / request   |
| Anthropic — roadmap from brief          | Variable | ~$0.30 / request   |
| Stripe transaction fee                 | Variable | 2.9% + $0.30 / pay |

Variable Anthropic cost dominates once free signups outpace ~50.
Stripe fees are negligible until Pro count > ~20.

---

## 3. Scenario assumptions

### Conservative

| Driver                          | Value                            |
|---------------------------------|----------------------------------|
| V at month 0 (launch)            | 200                              |
| V steady-state                   | 200 (no growth)                  |
| `s` (free signup rate)           | 5%                               |
| `h` (cap-hit rate)               | 5%                               |
| `c` (free→Pro)                   | 1%                               |
| `k` (Pro churn / month)          | 10%                              |
| `P` (Pro price)                  | $15                              |
| Phase 5 ships                    | Month 7 (gate A barely passes)   |
| Phase 6 ships                    | Never (gate B fails)             |

### Base

| Driver                          | Value                            |
|---------------------------------|----------------------------------|
| V at month 0 (launch)            | 500                              |
| V steady-state                   | 600 (modest organic growth)      |
| `s`                              | 8%                               |
| `h`                              | 8%                               |
| `c`                              | 3%                               |
| `k`                              | 5%                               |
| `P`                              | $15                              |
| Phase 5 ships                    | Month 5                          |
| Phase 6 ships                    | Month 9                          |

### Optimistic

| Driver                          | Value                            |
|---------------------------------|----------------------------------|
| V at month 0 (launch)            | 2,000 (HN front-page launch)     |
| V steady-state                   | 1,500 (post-spike + organic)     |
| `s`                              | 12%                              |
| `h`                              | 15%                              |
| `c`                              | 5%                               |
| `k`                              | 3%                               |
| `P`                              | $15                              |
| Phase 5 ships                    | Month 4                          |
| Phase 6 ships                    | Month 7                          |

---

## 4. 12-month projection

### Conservative scenario

Gate B fails — free-tier retention or cap-hit rate is too weak
to justify shipping Stripe. No paid revenue lands inside the
12-month horizon.

| Month | Phase | F (free) | Pro | MRR  |
|-------|-------|----------|-----|------|
| 0     | 4     | 10       | 0   | $0   |
| 3     | 4     | 40       | 0   | $0   |
| 6     | 4     | 70       | 0   | $0   |
| 7     | 5     | 80       | 0   | $0   |
| 9     | 5     | 100      | 0   | $0   |
| 12    | 5     | 130      | 0   | $0   |

- **Year 1 revenue:** $0
- **Year 1 cost:** ~$450 total (~$300 fixed infra over Phases 4–5,
  ~$120 Anthropic API for free-tier roadmaps, ~$30 domain / misc)
- **Net:** ~$450 burn, all unrecouped
- **Outcome:** pivot per the [ROADMAP §4 gate-A pivot list](ROADMAP.md#validation-gate--before-phase-5)
  or wind down

### Base scenario

Both gates pass; Pro launches month 9. Revenue ramps slowly
because Pro net-adds compound off a still-small free base.

| Month | Phase | F (free) | Pro | MRR   |
|-------|-------|----------|-----|-------|
| 0     | 4     | 40       | 0   | $0    |
| 1     | 4     | 88       | 0   | $0    |
| 3     | 4     | 184      | 0   | $0    |
| 5     | 5     | 280      | 0   | $0    |
| 7     | 5     | 376      | 0   | $0    |
| 9     | 6     | 472      | 1   | $15   |
| 10    | 6     | 520      | 2   | $30   |
| 11    | 6     | 568      | 3   | $45   |
| 12    | 6     | 616      | 5   | $75   |

(Pro net-add at month 12 ≈ `616 × 0.08 × 0.03 = 1.5` per month;
churn drag is small on a count this size.)

- **Year 1 revenue:** ~$165 (sum of MRR months 9–12)
- **Year 1 cost:** ~$960 (~$300 fixed + ~$640 Anthropic API +
  ~$20 Stripe / domain)
- **Net:** ~$795 burn in year 1
- **Run-rate at month 12:** $75 MRR → $900 ARR
- **Year 2 outlook:** Pro count compounds (free base keeps
  growing at +48 / month). At month 24, Pro ≈ 30, MRR ≈ $450,
  ARR ≈ $5,400 — break-even on monthly variable cost around
  month 16–18

### Optimistic scenario

| Month | Phase | F (free) | Pro | MRR    |
|-------|-------|----------|-----|--------|
| 0     | 4     | 240      | 0   | $0     |
| 3     | 4     | 780      | 0   | $0     |
| 4     | 5     | 960      | 0   | $0     |
| 6     | 5     | 1,320    | 0   | $0     |
| 7     | 6     | 1,500    | 11  | $165   |
| 8     | 6     | 1,680    | 23  | $345   |
| 9     | 6     | 1,860    | 36  | $540   |
| 10    | 6     | 2,040    | 50  | $750   |
| 11    | 6     | 2,220    | 65  | $975   |
| 12    | 6     | 2,400    | 81  | $1,215 |

(Pro net-add at month 12 ≈ `2,400 × 0.15 × 0.05 = 18` per month;
3% churn on 65-strong base is ~2.)

- **Year 1 revenue:** ~$3,990 (sum of MRR months 7–12)
- **Year 1 cost:** ~$3,260 (~$360 fixed + ~$2,700 Anthropic API
  + ~$200 Stripe / domain)
- **Net:** ~$730 contribution year 1
- **Run-rate at month 12:** $1,215 MRR → $14,580 ARR
- **Year 2 outlook:** if traffic and conversion hold, Pro ≈ 200
  by month 24 → MRR ≈ $3,000 → ARR ≈ $36k

---

## 5. Sensitivity analysis (base scenario, month 12)

Holding the base scenario constant except for one driver, month-
12 MRR moves as follows:

| Lever change                    | Month-12 MRR  | Δ vs base |
|---------------------------------|---------------|-----------|
| **Base scenario**                | $75           | —         |
| 2× visitors (1,200 / month)      | $180          | +140%     |
| 2× signup rate (16%)             | $180          | +140%     |
| 2× cap-hit rate (16%)            | $150          | +100%     |
| 2× conversion rate (6%)          | $150          | +100%     |
| ½ churn (2.5%)                   | $100          | +33%      |
| Price $19 vs $15                 | $95           | +27%      |
| 2× visitors AND 2× conversion    | $360          | +380%     |

Top-of-funnel drivers (visitors, signup rate) and conversion
dominate over churn and pricing in year 1. **Spend cycles on
distribution, not on retention features, in months 0–12.**
Retention starts to matter materially in year 2 once the Pro
base exceeds ~30 and the absolute monthly churn count exceeds
new monthly Pro adds.

---

## 6. Year-1 summary across scenarios

| Scenario     | Y1 Revenue | Y1 Cost | Y1 Net  | M12 ARR run-rate |
|--------------|-----------:|--------:|--------:|-----------------:|
| Conservative | $0         | ~$450   | −$450   | $0               |
| Base         | ~$165      | ~$960   | −$795   | ~$900            |
| Optimistic   | ~$3,990    | ~$3,260 | +$730   | ~$14,580         |

Year 1 is **not the story**. Even the optimistic case nets ~$700
contribution, which is rounding error against the user's current
$2,000/month Cursor overage. The honest framing: year 1 is the
**validation period**; year 2 is where compounding either
delivers or doesn't.

A solo operator should set personal expectations to:

- **Month 12 ARR ≥ $5k** = "this is real, keep going"
- **Month 12 ARR ≥ $15k** = "this is a side income"
- **Month 12 ARR ≥ $50k** = optimistic upper bound; would
  require either Team-tier inbound or breakout viral traction

Anything below $5k ARR at month 12 means the standalone advisor
framing isn't it — pivot per the
[ROADMAP §4 gate-A pivot list](ROADMAP.md#validation-gate--before-phase-5).

---

## 7. What this pro-forma deliberately does not model

- **SEO compounding.** Long-tail organic traffic typically
  doubles month-over-month for the first 6–12 months of a
  content-led launch. Not modeled because keyword strategy isn't
  set yet.
- **Viral / referral.** A "Made with roadmodel" footer link
  on every shared roadmap could meaningfully increase `V(t)`.
  Not modeled because it requires real launch data to
  calibrate.
- **Annual prepay.** Offering 12-months-for-10 reduces churn and
  bumps cash flow but distorts MRR comparisons. Not modeled.
- **Team / Enterprise revenue.** Out of scope per
  [ROADMAP.md](ROADMAP.md) §7.
- **Anthropic price changes.** Modeled at current Haiku 4.5 +
  Sonnet 4.6 rates; lineup shifts flow through the weekly
  auto-refresh in `docs/`.
- **Free-user churn.** Held at 0% to keep formulas simple; in
  practice 5–10% / month is realistic and would compress `F(t)`
  by ~20–30% over 12 months.
- **Refunds and chargebacks.** Held at 0%. Add ~1% of revenue
  if you want a defensive estimate.

---

## 8. How to update this doc

1. Edit assumptions in §3.
2. Re-walk the formulas in §1 forward month by month — easiest
   in a spreadsheet; copy the resulting numbers back into §4.
3. Re-run sensitivity in §5 against whichever lever you most
   want to defend.
4. Once a real launch happens, replace assumed `V`, `s`, `h`,
   `c`, `k` with measured values from the observability stack
   (Phase 4.4) and Stripe (Phase 6.5). At that point this doc
   stops being a pro-forma and becomes a budget.
