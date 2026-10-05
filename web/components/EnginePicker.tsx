// web/components/EnginePicker.tsx
//
// The /recommend engine menu: which model READS the task and WRITES the three
// picks. Every option shows what the choice costs and how it did on the
// engine eval (scripts/eval_recommend_engines.py): the measured cost of one
// recommendation, its typical time, and how many of the 12 probe tasks it
// answered in full. Engines the visitor may not use are listed, locked, with
// the reason, so the menu is the same for everyone and nothing is hidden.
//
// A listbox in a popover: the trigger names the current engine; arrows move,
// Enter or Space chooses, Escape or a click outside closes.
"use client";

import { Check, ChevronDown, Lock } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { cents, costLine, costNote, lockReason, seconds } from "@/lib/engine-format";
import type { EngineOption } from "@/lib/recommend-engines";

function costOf(o: EngineOption): number {
  return o.eval?.mean_cost_usd ?? o.warmUsd;
}

function OptionFigures({ o }: { o: EngineOption }) {
  const e = o.eval;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
      <span title={costNote(o.payer)}>{costLine(o.payer, costOf(o))}</span>
      {e?.p50_latency_s != null && <span title="Median time on the engine eval">~{seconds(e.p50_latency_s)}</span>}
      {e ? (
        <span title={`Engine eval, ${e.evaluated_on}: answered every structured field on ${e.passed} of ${e.probes} probe tasks`}>
          {e.passed}/{e.probes} probes
        </span>
      ) : (
        <span>not yet evaluated</span>
      )}
    </span>
  );
}

export function EnginePicker({
  options,
  value,
  onChange,
  signedIn,
  disabled = false,
}: {
  options: EngineOption[];
  value: string;
  onChange: (hint: string) => void;
  signedIn: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => Math.max(0, options.findIndex((o) => o.hint === value)));
  const wrap = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const current = options.find((o) => o.hint === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, options.findIndex((o) => o.hint === value)));
    list.current?.focus();
    const away = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, options, value]);

  function choose(i: number) {
    const o = options[i];
    if (!o || !o.allowed) return;
    onChange(o.hint);
    setOpen(false);
    button.current?.focus();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(options.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(options.length - 1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      choose(active);
    }
  }

  if (!current) return null;

  return (
    <div ref={wrap} className="relative">
      <button
        ref={button}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        data-testid="engine-picker"
        onClick={() => setOpen((o) => !o)}
        className="group flex min-w-0 items-center gap-2 rounded-lg border border-brand-slate-300 bg-white px-3 py-2 text-left text-sm shadow-sm transition hover:border-brand-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent/40 disabled:opacity-60 dark:border-brand-slate-600 dark:bg-brand-slate-800"
      >
        <span className="text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400">Engine</span>
        <span className="truncate font-semibold text-brand-slate-900 dark:text-brand-slate-50" data-testid="engine-current">
          {current.name}
        </span>
        <span className="hidden text-xs tabular-nums text-brand-slate-500 sm:inline dark:text-brand-slate-400">
          {cents(costOf(current))}
          {current.eval?.p50_latency_s != null ? ` · ~${seconds(current.eval.p50_latency_s)}` : ""}
        </span>
        <ChevronDown className="h-4 w-4 flex-none text-brand-slate-400 transition group-aria-expanded:rotate-180" aria-hidden />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-[min(30rem,calc(100vw-2rem))] rounded-xl border border-brand-slate-200 bg-white p-2 shadow-xl shadow-brand-slate-900/10 dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:shadow-black/40 sm:bottom-auto sm:top-full sm:mb-0 sm:mt-2">
          <p className="px-2 pb-2 pt-1 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
            The engine reads your task and writes the three picks; it is not the model it
            recommends. Cost is what one recommendation costs at the engine&rsquo;s API price
            {current.payer === "visitor" ? ", billed to your key." : ", paid by roadmodel."}
          </p>
          <ul
            ref={list}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label="Recommendation engine"
            aria-activedescendant={`${listId}-${active}`}
            onKeyDown={onKey}
            className="max-h-[22rem] overflow-y-auto outline-none"
            data-testid="engine-options"
          >
            {options.map((o, i) => {
              const selected = o.hint === value;
              return (
                <li
                  key={o.hint}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={selected}
                  aria-disabled={!o.allowed}
                  data-engine={o.hint}
                  data-allowed={o.allowed ? "1" : "0"}
                  onPointerEnter={() => setActive(i)}
                  onClick={() => choose(i)}
                  className={
                    "flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 " +
                    (i === active ? "bg-brand-slate-100 dark:bg-brand-slate-700/60 " : "") +
                    (o.allowed ? "" : "cursor-not-allowed opacity-60")
                  }
                >
                  <span className="mt-0.5 flex h-4 w-4 flex-none items-center justify-center">
                    {selected ? (
                      <Check className="h-4 w-4 text-brand-accent" aria-hidden />
                    ) : !o.allowed ? (
                      <Lock className="h-3.5 w-3.5 text-brand-slate-400" aria-hidden />
                    ) : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">{o.name}</span>
                      <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">{o.maker}</span>
                      {o.isDefault && (
                        <span className="rounded-full bg-brand-accent/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-brand-accent">
                          Default
                        </span>
                      )}
                      {!o.allowed && (
                        <span className="text-[11px] font-medium text-brand-slate-500 dark:text-brand-slate-400">
                          {lockReason(o.access, signedIn, o.evaluated)}
                        </span>
                      )}
                    </span>
                    <OptionFigures o={o} />
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
