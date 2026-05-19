// web/components/SettingsList.tsx
interface SettingsListProps {
  settings: Record<string, unknown>;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function SettingsList({ settings }: SettingsListProps) {
  const entries = Object.entries(settings);
  if (entries.length === 0) {
    return null;
  }

  return (
    <dl className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-2 gap-2 text-sm">
          <dt className="font-medium text-brand-slate-600">{key}</dt>
          <dd className="text-brand-slate-900">{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
