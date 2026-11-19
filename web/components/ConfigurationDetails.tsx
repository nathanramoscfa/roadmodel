import { Fragment } from "react";

import type { AgentConfiguration, AgentConfigurationRow } from "@/lib/catalog-fields";
import { effortWord } from "@/lib/pick-effort";

const SOURCE_LINK = "text-brand-accent hover:underline";

export function configurationLevel(configuration: AgentConfiguration): string {
  if (!configuration.effort) return "Fixed";
  const effort = effortWord(configuration.effort);
  return configuration.settings.ultracode === "On" ? `${effort} · Ultracode On` : effort;
}

export function ConfigurationEvidence({ configuration }: { configuration: AgentConfiguration }) {
  if (!configuration.evidenceSource) return null;
  return (
    <a href={configuration.evidenceSource} target="_blank" rel="noopener noreferrer" className={SOURCE_LINK}>
      Configuration evidence
    </a>
  );
}

export function ConfigurationDetail({ model, showPlatform = true }: {
  model: AgentConfigurationRow;
  showPlatform?: boolean;
}) {
  const { configuration } = model;
  const benchmark = configuration.benchmarkNote;
  return (
    <div className="space-y-2 text-sm text-brand-slate-600 dark:text-brand-slate-300">
      {(showPlatform || configuration.roles.length === 0) && <p>{model.best_for}</p>}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
        {showPlatform && <><dt>Platform</dt><dd>{configuration.platform}</dd></>}
        <dt>Level</dt><dd>{configurationLevel(configuration)}</dd>
        {configuration.roles.map(({ role, model: name }) => (
          <Fragment key={role}><dt>{role}</dt><dd>{name}</dd></Fragment>
        ))}
        <dt>Availability</dt><dd>{configuration.availability}</dd>
      </dl>
      {benchmark && (
        <p>
          {benchmark.summary}{" "}
          <a href={benchmark.source} target="_blank" rel="noopener noreferrer" className={SOURCE_LINK}>
            Google’s benchmark results
          </a>
        </p>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <ConfigurationEvidence configuration={configuration} />
        <a href={configuration.source} target="_blank" rel="noopener noreferrer" className={SOURCE_LINK}>
          Platform documentation
        </a>
      </div>
    </div>
  );
}

export function PlatformDetails({ configurations }: { configurations: AgentConfigurationRow[] }) {
  if (!configurations.length) return null;
  const groups = new Map<string, AgentConfigurationRow[]>();
  for (const model of configurations) {
    const platform = model.configuration.platform;
    const group = groups.get(platform);
    if (group) group.push(model);
    else groups.set(platform, [model]);
  }

  return (
    <section id="platform-details" aria-labelledby="platform-details-heading" className="scroll-mt-20 space-y-4">
      <div>
        <h2 id="platform-details-heading" className="text-xl font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Platform details
        </h2>
        <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          These agent configurations are available to select and are awaiting comparable benchmarks and costs.
        </p>
      </div>
      {[...groups].map(([platform, models]) => (
        <div key={platform} className="space-y-2">
          <h3 className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{platform}</h3>
          <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {models.map((model) => (
              <li key={model.id} className="space-y-2 rounded-lg border border-brand-slate-200 p-4 dark:border-brand-slate-700">
                <h4 className="font-medium text-brand-slate-900 dark:text-brand-slate-50">{model.name}</h4>
                <ConfigurationDetail model={model} showPlatform={false} />
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
