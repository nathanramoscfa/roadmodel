// web/lib/keyless-eval.ts
//
// The keyless lane's measured agreement with the AI recommender, read from the
// build's copy of docs/keyless-eval.json (scripts/sync-catalog.mjs). Only this
// copy is read, so the sentence on /recommend follows a re-run of
// scripts/eval_keyless_agreement.py with no code change. Server-side: the page
// passes the four figures down, so the file stays out of the client bundle.

import evalRecord from "@/data/keyless-eval.json";

import type { KeylessAgreement } from "./keyless";

export function keylessAgreement(): KeylessAgreement {
  const r = evalRecord as { agree: number; total: number; evaluated_on: string; probes: unknown[] };
  return { agree: r.agree, total: r.total, tasks: r.probes.length, evaluatedOn: r.evaluated_on };
}
