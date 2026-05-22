// web/components/RoadmapTabSwitcher.tsx
"use client";

export type RoadmapTab = "chat" | "preview";

interface RoadmapTabSwitcherProps {
  activeTab: RoadmapTab;
  onChange: (tab: RoadmapTab) => void;
}

export function RoadmapTabSwitcher({
  activeTab,
  onChange,
}: RoadmapTabSwitcherProps) {
  const tabs: { id: RoadmapTab; label: string }[] = [
    { id: "chat", label: "Chat" },
    { id: "preview", label: "Preview" },
  ];

  return (
    <div
      className="mb-4 flex gap-2 md:hidden"
      role="tablist"
      aria-label="Roadmap panels"
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={
              (isActive
                ? "bg-brand-accent text-white "
                : "bg-brand-slate-100 text-brand-slate-700 ") +
              "rounded-full px-4 py-2 text-sm font-semibold transition"
            }
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
