// web/components/ModelHeader.tsx
interface ModelHeaderProps {
  model: string;
  platform: string;
}

export function ModelHeader({ model, platform }: ModelHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <h2 className="text-2xl font-bold text-brand-slate-900">{model}</h2>
      <span
        className={
          "inline-flex rounded-full bg-brand-accent-muted px-3 py-1 " +
          "text-xs font-medium text-brand-accent"
        }
      >
        {platform}
      </span>
    </div>
  );
}
