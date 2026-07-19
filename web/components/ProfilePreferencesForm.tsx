// web/components/ProfilePreferencesForm.tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Type-only imports: importing a VALUE from @/lib/profile or
// @/lib/subscriptions pulls in server-only modules (next/headers,
// catalog.json) and breaks this client component's build. The default
// jurisdiction list is a local literal; the catalog-derived subscription
// options arrive as a prop from the server page (issue #152, #154).
import type {
  ApiProviderId,
  BudgetPriority,
  ConsumptionHeadroom,
  JurisdictionCode,
  SubscriptionId,
} from "@/lib/profile";
import type { ApiProviderOption } from "@/lib/api-providers";
import type { SubscriptionOption } from "@/lib/subscriptions";
import { BUDGET_PRIORITY_OPTIONS } from "@/lib/budget-priority";
import { CONSUMPTION_HEADROOM_OPTIONS } from "@/lib/consumption-headroom";

// The "low-risk" jurisdiction set — what the "Restrict to low-risk
// jurisdictions" toggle narrows to, and the chips shown when it's on. Excludes
// cn / ru / unknown.
export const LOW_RISK_JURISDICTIONS: JurisdictionCode[] = [
  "us",
  "eu",
  "uk",
  "ca",
  "au",
  "jp",
  "kr",
];

// The DEFAULT allowed set for a new profile / onboarding — low-risk PLUS cn
// (#445), so mainstream Chinese open-weight models are available by default and
// the restrict toggle starts OFF. Mirrors DEFAULT_PROFILE.allowed_jurisdictions
// (kept as a literal so this client component doesn't import a server-coupled
// value). Exported for the onboarding wrapper's default.
export const DEFAULT_JURISDICTIONS: JurisdictionCode[] = [
  ...LOW_RISK_JURISDICTIONS,
  "cn",
];

// Provider home-jurisdictions considered low-risk — the set an API provider
// must fall in to remain visible when the restrict toggle is on. Mirrors
// LOW_RISK_JURISDICTIONS (provider_jurisdiction uses the same country codes).
const LOW_RISK_PROVIDER_JURISDICTIONS: ReadonlySet<string> = new Set(
  LOW_RISK_JURISDICTIONS,
);

const ALL_JURISDICTIONS: { id: JurisdictionCode; label: string }[] = [
  { id: "us", label: "United States" },
  { id: "eu", label: "European Union" },
  { id: "uk", label: "United Kingdom" },
  { id: "ca", label: "Canada" },
  { id: "au", label: "Australia" },
  { id: "jp", label: "Japan" },
  { id: "kr", label: "South Korea" },
  { id: "cn", label: "China" },
  { id: "ru", label: "Russia" },
  { id: "unknown", label: "Unknown" },
];

function sameJurisdictionSet(
  a: JurisdictionCode[],
  b: JurisdictionCode[],
): boolean {
  if (a.length !== b.length) return false;
  const setB = new Set(b);
  return a.every((j) => setB.has(j));
}

const MONEY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  // Drop the cents on whole dollars ("$200", not "$200.00") but keep them
  // where they matter ("$4.99"). The currency style defaults the minimum
  // to 2, so set it explicitly to 0.
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

// Format a USD amount currency-grouped, dropping the cents on whole dollars
// ("$200", "$2,000", "$4.99"). Used for the subscription price column.
function formatMoney(usd: number): string {
  return MONEY.format(usd);
}

// The catalog bakes a "($NNN)" price disambiguator into a few tier names
// (the two "Claude Max" rows, etc.). The price column now disambiguates
// them, so strip the parenthetical for display (Phase 4.7 T1).
function displayName(label: string): string {
  return label.replace(/\s*\(\$[\d.,]+\)\s*$/, "");
}

// Build the price-column text for a tier: monthly only ("$N/mo"). The catalog
// seeds a verified annual price for only a few tiers, so rendering "· $Y/yr
// (save Z%)" produced an inconsistent column (some tiers had it, most didn't).
// annual_usd stays in the data model (catalog-owned) but is no longer shown.
function priceLabel(monthly: number): string {
  return `${formatMoney(monthly)}/mo`;
}

export interface ProfilePreferencesFormProps {
  // Catalog-derived subscription options, passed from the server page so
  // the large catalog.json stays out of the client bundle (issue #152).
  subscriptionOptions: SubscriptionOption[];
  initialSubscriptions: SubscriptionId[];
  // Catalog-derived API-provider options (Phase 4.8, #260), passed from the
  // server page alongside the subscription options.
  apiProviderOptions: ApiProviderOption[];
  initialApiProviders: ApiProviderId[];
  initialBudgetPriority: BudgetPriority;
  initialConsumptionHeadroom: ConsumptionHeadroom;
  initialJurisdictions: JurisdictionCode[];
  submitLabel: string;
  // Onboarding redirects to `next` after save. Settings stays on the page
  // and shows an inline confirmation (redirectOnSave === null).
  redirectOnSave: string | null;
  // Onboarding offers a "Skip for now" affordance; settings does not.
  skipLabel?: string;
}

export function ProfilePreferencesForm({
  subscriptionOptions,
  initialSubscriptions,
  apiProviderOptions,
  initialApiProviders,
  initialBudgetPriority,
  initialConsumptionHeadroom,
  initialJurisdictions,
  submitLabel,
  redirectOnSave,
  skipLabel,
}: ProfilePreferencesFormProps) {
  const router = useRouter();
  const [subscriptions, setSubscriptions] =
    useState<SubscriptionId[]>(initialSubscriptions);
  const [apiProviders, setApiProviders] =
    useState<ApiProviderId[]>(initialApiProviders);
  const [budgetPriority, setBudgetPriority] =
    useState<BudgetPriority>(initialBudgetPriority);
  const [consumptionHeadroom, setConsumptionHeadroom] =
    useState<ConsumptionHeadroom>(initialConsumptionHeadroom);
  const [restrictLowRisk, setRestrictLowRisk] = useState(
    sameJurisdictionSet(initialJurisdictions, LOW_RISK_JURISDICTIONS),
  );
  const [customJurisdictions, setCustomJurisdictions] = useState<
    JurisdictionCode[]
  >(initialJurisdictions.length > 0 ? initialJurisdictions : DEFAULT_JURISDICTIONS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function toggleSubscription(id: SubscriptionId): void {
    setSaved(false);
    setSubscriptions((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  function toggleApiProvider(id: ApiProviderId): void {
    setSaved(false);
    setApiProviders((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  }

  function toggleJurisdiction(id: JurisdictionCode): void {
    setSaved(false);
    setCustomJurisdictions((prev) => {
      if (prev.includes(id)) {
        const nextList = prev.filter((j) => j !== id);
        return nextList.length > 0 ? nextList : prev;
      }
      return [...prev, id];
    });
  }

  function allowedJurisdictions(): JurisdictionCode[] {
    return restrictLowRisk ? LOW_RISK_JURISDICTIONS : customJurisdictions;
  }

  // API providers whose home jurisdiction survives the low-risk filter. When
  // the toggle is on, higher-risk providers (e.g. DeepSeek / z.ai, both cn) are
  // hidden — offering a vendor the jurisdiction filter will then exclude is
  // misleading (#445).
  const visibleApiProviderOptions = restrictLowRisk
    ? apiProviderOptions.filter((o) =>
        LOW_RISK_PROVIDER_JURISDICTIONS.has(o.jurisdiction),
      )
    : apiProviderOptions;

  // Effective API-provider selection: never persist a provider that is hidden
  // by the active jurisdiction filter, so a stale cn selection can't linger.
  function effectiveApiProviders(): ApiProviderId[] {
    if (!restrictLowRisk) return apiProviders;
    const visible = new Set(visibleApiProviderOptions.map((o) => o.id));
    return apiProviders.filter((id) => visible.has(id));
  }

  // Toggling the restrict filter ON prunes any now-hidden provider from the
  // live selection so the checkboxes and the saved value stay consistent.
  function handleRestrictLowRiskChange(checked: boolean): void {
    setSaved(false);
    setRestrictLowRisk(checked);
    if (checked) {
      setApiProviders((prev) =>
        prev.filter((id) => {
          const option = apiProviderOptions.find((o) => o.id === id);
          return option
            ? LOW_RISK_PROVIDER_JURISDICTIONS.has(option.jurisdiction)
            : true;
        }),
      );
    }
  }

  async function saveProfile(body: Record<string, unknown>): Promise<void> {
    setPending(true);
    setError(null);
    const res = await fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setPending(false);
    if (!res.ok) {
      setError("Could not save your preferences. Please try again.");
      return;
    }
    if (redirectOnSave) {
      router.push(redirectOnSave);
      return;
    }
    setSaved(true);
    router.refresh();
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await saveProfile({
      subscriptions,
      api_providers: effectiveApiProviders(),
      budget_priority: budgetPriority,
      consumption_headroom: consumptionHeadroom,
      allowed_jurisdictions: allowedJurisdictions(),
      skip: false,
    });
  }

  async function handleSkip(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    // `skip` is only offered when redirectOnSave is set (onboarding), so
    // saveProfile performs the redirect; no extra navigation needed here.
    await saveProfile({ skip: true });
  }

  // Group the catalog-derived options by provider, preserving first-seen
  // order (the order they appear in the catalog).
  const groupedSubscriptions: { provider: string; options: SubscriptionOption[] }[] = [];
  for (const option of subscriptionOptions) {
    const group = groupedSubscriptions.find((g) => g.provider === option.provider);
    if (group) {
      group.options.push(option);
    } else {
      groupedSubscriptions.push({ provider: option.provider, options: [option] });
    }
  }

  return (
    <form onSubmit={handleSave} className="mt-8 flex flex-col gap-8">
      <fieldset>
        <legend className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Active subscriptions
        </legend>
        <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          Select every subscription you pay for today.
        </p>
        <div className="mt-4 flex flex-col gap-5">
          {groupedSubscriptions.map((group) => (
            <div key={group.provider} className="flex flex-col gap-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
                {group.provider}
              </p>
              {group.options.map((option) => (
                <label
                  key={option.id}
                  className="flex items-center justify-between gap-3 text-sm text-brand-slate-800 dark:text-brand-slate-100"
                >
                  <span className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={subscriptions.includes(option.id)}
                      onChange={() => toggleSubscription(option.id)}
                      className="rounded border-brand-slate-300 dark:border-brand-slate-700 accent-brand-accent"
                    />
                    {displayName(option.label)}
                  </span>
                  <span className="tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
                    {priceLabel(option.monthly_usd)}
                  </span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </fieldset>

      {apiProviderOptions.length > 0 ? (
        <fieldset>
          <legend className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
            API access
          </legend>
          <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
            Select any provider you also use directly via your own API key
            (pay-per-token). We never store your keys — this just lets us weigh
            API cost against the subscriptions you already pay for.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            {visibleApiProviderOptions.map((option) => (
              <label
                key={option.id}
                className="flex items-center gap-2 text-sm text-brand-slate-800 dark:text-brand-slate-100"
              >
                <input
                  type="checkbox"
                  checked={apiProviders.includes(option.id)}
                  onChange={() => toggleApiProvider(option.id)}
                  className="rounded border-brand-slate-300 dark:border-brand-slate-700 accent-brand-accent"
                />
                {option.label}
              </label>
            ))}
            {restrictLowRisk &&
            visibleApiProviderOptions.length < apiProviderOptions.length ? (
              <p className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
                Some providers are hidden because “Restrict to low-risk
                jurisdictions” is on. Uncheck it below to use providers based in
                other jurisdictions.
              </p>
            ) : null}
          </div>
        </fieldset>
      ) : null}

      <fieldset>
        <legend className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Budget priority
        </legend>
        <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          How aggressively should we optimize for cost vs. quality?
        </p>
        <div className="mt-4 flex flex-wrap gap-4">
          {BUDGET_PRIORITY_OPTIONS.map((option) => (
            <label
              key={option.id}
              className="flex items-center gap-2 text-sm text-brand-slate-800 dark:text-brand-slate-100"
            >
              <input
                type="radio"
                name="budget_priority"
                value={option.id}
                checked={budgetPriority === option.id}
                onChange={() => {
                  setSaved(false);
                  setBudgetPriority(option.id);
                }}
                className="accent-brand-accent"
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Reasoning effort
        </legend>
        <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          Effort is separate from which model we pick. Higher effort is only
          worth trading away when it costs you — per-token spend or a usage limit
          you actually hit.
        </p>
        <div className="mt-4 flex flex-col gap-3">
          {CONSUMPTION_HEADROOM_OPTIONS.map((option) => (
            <label
              key={option.id}
              className="flex items-start gap-2 text-sm text-brand-slate-800 dark:text-brand-slate-100"
            >
              <input
                type="radio"
                name="consumption_headroom"
                value={option.id}
                checked={consumptionHeadroom === option.id}
                onChange={() => {
                  setSaved(false);
                  setConsumptionHeadroom(option.id);
                }}
                className="mt-0.5 accent-brand-accent"
              />
              <span className="flex flex-col">
                <span className="font-medium">{option.label}</span>
                <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
                  {option.hint}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <details
        open={advancedOpen}
        onToggle={(event) =>
          setAdvancedOpen((event.target as HTMLDetailsElement).open)
        }
        className="rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800"
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-brand-slate-800 dark:text-brand-slate-100">
          Advanced: jurisdiction filter
        </summary>
        <div className="space-y-4 border-t border-brand-slate-200 dark:border-brand-slate-700 px-4 py-4">
          <label className="flex items-start gap-2 text-sm text-brand-slate-800 dark:text-brand-slate-100">
            <input
              type="checkbox"
              checked={restrictLowRisk}
              onChange={(event) =>
                handleRestrictLowRiskChange(event.target.checked)
              }
              className="mt-0.5 rounded border-brand-slate-300 dark:border-brand-slate-700 accent-brand-accent"
            />
            <span>
              Restrict to low-risk jurisdictions — hides providers based in
              China and other higher-risk regions
            </span>
          </label>
          {restrictLowRisk ? (
            <div className="flex flex-wrap gap-2">
              {LOW_RISK_JURISDICTIONS.map((code) => (
                <span
                  key={code}
                  className={
                    "rounded-full bg-brand-slate-100 dark:bg-brand-slate-800 px-3 py-1 text-xs " +
                    "font-medium uppercase tracking-wide text-brand-slate-700 dark:text-brand-slate-200"
                  }
                >
                  {code}
                </span>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-brand-slate-600 dark:text-brand-slate-300">
                Explicitly choose which jurisdictions may appear in
                recommendations. Check China or Russia only if you accept
                the provider risk.
              </p>
              {ALL_JURISDICTIONS.map((option) => (
                <label
                  key={option.id}
                  className="flex items-center gap-2 text-sm text-brand-slate-800 dark:text-brand-slate-100"
                >
                  <input
                    type="checkbox"
                    checked={customJurisdictions.includes(option.id)}
                    onChange={() => toggleJurisdiction(option.id)}
                    className="rounded border-brand-slate-300 dark:border-brand-slate-700"
                  />
                  {option.label} ({option.id})
                </label>
              ))}
            </div>
          )}
        </div>
      </details>

      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p className="text-sm text-green-600" role="status">
          Preferences saved.
        </p>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <button
          type="submit"
          disabled={pending}
          className={
            "rounded-lg bg-brand-accent px-6 py-3 text-sm font-semibold " +
            "text-white shadow-sm hover:bg-brand-accent/90 disabled:opacity-60"
          }
        >
          {pending ? "Saving…" : submitLabel}
        </button>
        {skipLabel ? (
          <button
            type="button"
            onClick={handleSkip}
            disabled={pending}
            className="text-sm font-medium text-brand-accent hover:underline"
          >
            {skipLabel}
          </button>
        ) : null}
      </div>
    </form>
  );
}
