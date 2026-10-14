// web/lib/use-saved-recommendations.ts
//
// /recommend's saved list for one account: what lib/saved-store.ts holds in
// this browser, newest first, kept current when another tab changes it. Saving,
// deleting and clearing update the list at once and write behind it, so a
// browser that refuses storage still shows this visit's results.
"use client";

import { useCallback, useEffect, useState } from "react";

import { MAX_IMPORT_BYTES, MAX_SAVED, exportFile, parseImport, type SavedRun } from "./saved-recommendations";
import { addSaved, adoptLegacy, clearSaved, deleteSaved, importSaved, listSaved, onSavedMessage } from "./saved-store";

export interface SavedStatus {
  text: string;
  error: boolean;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function download(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function useSavedRecommendations(owner: string) {
  const [runs, setRuns] = useState<SavedRun[]>([]);
  const [status, setStatus] = useState<SavedStatus | null>(null);

  useEffect(() => {
    let current = true;
    setRuns([]);
    setStatus(null);
    const reload = () => listSaved(owner).then((list) => { if (current) setRuns(list); });
    void adoptLegacy(owner).then(reload);
    const off = onSavedMessage((message) => {
      if (message.type === "removed-all" || (message.type === "changed" && message.owner === owner)) void reload();
    });
    return () => { current = false; off(); };
  }, [owner]);

  const save = useCallback((run: SavedRun) => {
    setRuns((prev) => [run, ...prev.filter((r) => r.id !== run.id)].slice(0, MAX_SAVED));
    void addSaved(owner, run);
  }, [owner]);

  const remove = useCallback((run: SavedRun) => {
    setRuns((prev) => prev.filter((r) => r.id !== run.id));
    setStatus(null);
    void deleteSaved(owner, run.id);
  }, [owner]);

  const clear = useCallback(() => {
    setRuns([]);
    setStatus(null);
    void clearSaved(owner);
  }, [owner]);

  const exportAll = useCallback(() => {
    download(`roadmodel-recommendations-${new Date().toISOString().slice(0, 10)}.json`, exportFile(runs, new Date()));
    setStatus({ text: `Exported ${plural(runs.length, "recommendation")}.`, error: false });
  }, [runs]);

  const importFile = useCallback(async (file: File) => {
    const fail = (text: string) => setStatus({ text, error: true });
    const parsed = file.size > MAX_IMPORT_BYTES ? null : parseImport(await file.text().catch(() => ""));
    if (!parsed) return fail("That file is not a roadmodel export.");
    if (parsed.runs.length === 0) return fail("That file holds no recommendations this page can read.");
    const result = await importSaved(owner, parsed.runs);
    if (!result) return fail("This browser would not save them: its storage is full or turned off.");
    setRuns(await listSaved(owner));
    const notes = [`Imported ${plural(result.saved, "recommendation")}.`];
    if (parsed.skipped > 0) notes.push(parsed.skipped === 1 ? "1 entry could not be read and was skipped." : `${parsed.skipped} entries could not be read and were skipped.`);
    if (result.dropped > 0) notes.push(`The oldest ${result.dropped} were removed to keep ${MAX_SAVED}.`);
    setStatus({ text: notes.join(" "), error: false });
  }, [owner]);

  return { runs, status, save, remove, clear, exportAll, importFile };
}
