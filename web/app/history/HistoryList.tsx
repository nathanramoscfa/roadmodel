// web/app/history/HistoryList.tsx
"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import type { ConversationSummary } from "@/lib/roadmap-types";

interface HistoryListProps {
  conversations: ConversationSummary[];
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.valueOf())) {
    return iso;
  }
  return date.toISOString().slice(0, 10);
}

export function HistoryList({ conversations }: HistoryListProps) {
  const [titleInput, setTitleInput] = useState("");
  const [fromInput, setFromInput] = useState("");
  const [toInput, setToInput] = useState("");

  // Debounced mirrors so a fast typist doesn't re-run the filter
  // on every keystroke. The list is small (≤ 200 rows) so the
  // 300ms debounce is generous; spec calls it out explicitly.
  const [titleQuery, setTitleQuery] = useState("");
  const [fromQuery, setFromQuery] = useState("");
  const [toQuery, setToQuery] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setTitleQuery(titleInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [titleInput]);

  useEffect(() => {
    const handle = setTimeout(() => setFromQuery(fromInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [fromInput]);

  useEffect(() => {
    const handle = setTimeout(() => setToQuery(toInput.trim()), 300);
    return () => clearTimeout(handle);
  }, [toInput]);

  const filtered = useMemo(() => {
    const needle = titleQuery.toLowerCase();
    const fromIso = fromQuery ? new Date(fromQuery).toISOString() : null;
    const toIso = toQuery
      ? new Date(`${toQuery}T23:59:59.999Z`).toISOString()
      : null;
    return conversations.filter((c) => {
      if (needle && !c.title.toLowerCase().includes(needle)) {
        return false;
      }
      if (fromIso && c.updated_at < fromIso) {
        return false;
      }
      if (toIso && c.updated_at > toIso) {
        return false;
      }
      return true;
    });
  }, [conversations, titleQuery, fromQuery, toQuery]);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-brand-slate-700">Search title</span>
          <input
            type="search"
            value={titleInput}
            onChange={(e) => setTitleInput(e.target.value)}
            placeholder="Search by project name"
            aria-label="Search by project name"
            className={
              "rounded-md border border-brand-slate-300 bg-white px-3 py-2 " +
              "text-sm shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-1 focus:ring-brand-accent"
            }
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-brand-slate-700">From</span>
          <input
            type="date"
            value={fromInput}
            onChange={(e) => setFromInput(e.target.value)}
            aria-label="From date"
            className={
              "rounded-md border border-brand-slate-300 bg-white px-3 py-2 " +
              "text-sm shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-1 focus:ring-brand-accent"
            }
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-brand-slate-700">To</span>
          <input
            type="date"
            value={toInput}
            onChange={(e) => setToInput(e.target.value)}
            aria-label="To date"
            className={
              "rounded-md border border-brand-slate-300 bg-white px-3 py-2 " +
              "text-sm shadow-sm focus:border-brand-accent focus:outline-none " +
              "focus:ring-1 focus:ring-brand-accent"
            }
          />
        </label>
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-brand-slate-500">
          No conversations match your filters.
        </p>
      ) : (
        <ul className="space-y-3" data-testid="history-list">
          {filtered.map((c) => (
            <li
              key={c.id}
              data-testid="history-item"
              className={
                "flex flex-col gap-2 rounded-lg border border-brand-slate-200 " +
                "bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
              }
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-brand-slate-900">
                  {c.title}
                </p>
                {c.last_message_snippet ? (
                  <p className="mt-1 line-clamp-2 text-sm text-brand-slate-600">
                    {c.last_message_snippet}
                  </p>
                ) : null}
                <p className="mt-1 text-xs text-brand-slate-500">
                  Updated {formatDate(c.updated_at)}
                </p>
              </div>
              <Link
                href={`/roadmap/${c.id}`}
                className={
                  "inline-flex shrink-0 items-center justify-center rounded-md " +
                  "border border-brand-accent bg-brand-accent px-4 py-2 text-sm " +
                  "font-medium text-white shadow-sm hover:bg-brand-accent/90"
                }
              >
                Continue
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
