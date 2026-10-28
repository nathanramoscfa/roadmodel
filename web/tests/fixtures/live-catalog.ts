// web/tests/fixtures/live-catalog.ts
//
// data/catalog.json as the page renders it: without the rows past their leave
// date, which lib/catalog-models hides even while a stale catalog still lists
// them. Specs that count or derive from the rendered rows read this.

import { readFileSync } from "node:fs";
import path from "node:path";

import { pastLeaveDate } from "../../lib/catalog-models";

export function liveCatalog<T extends { models: object[] }>(now: Date = new Date()): T {
  const raw = JSON.parse(readFileSync(path.join(process.cwd(), "data", "catalog.json"), "utf8")) as T;
  const models = raw.models.filter(
    (m) => !pastLeaveDate((m as { retires_on?: string | null }).retires_on, now),
  );
  return { ...raw, models };
}
