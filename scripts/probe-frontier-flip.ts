// scripts/probe-frontier-flip.ts
//
// Focused post-deploy verification for the GPT-5 mini frontier flip (#474).
// Mints one founder session and fires ONE anon + ONE signed-in /api/recommend
// against gated prod, printing the raw client payload so we can read the
// `engine` field + tier attribution (frontier vs free) directly.
//
//   cd web
//   NODE_PATH="$(pwd)/node_modules" ../scripts/with-prod-secrets.sh \
//       node node_modules/.bin/tsx ../scripts/probe-frontier-flip.ts [BASE_URL]

import { createClient } from "@supabase/supabase-js";
import { createServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";

const BASE = process.argv[2] ?? "https://roadmodel.ai";
const EMAIL = process.env.ROADMODEL_DOGFOOD_EMAIL ?? "nathan.ramos.github@gmail.com";
const TASK =
  "Help me build a small Python CLI that fetches weather data and caches it locally.";

function need(n: string): string {
  const v = process.env[n];
  if (!v) {
    console.error(`missing env ${n}`);
    process.exit(2);
  }
  return v;
}
function gateToken(p: string): string {
  return createHash("sha256").update(`roadmodel-gate-v1:${p}`).digest("hex");
}

async function mintAuthCookie(): Promise<string> {
  const url = need("SUPABASE_URL");
  const admin = createClient(url, need("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false },
  });
  const { data, error } = await admin.auth.admin.generateLink({
    type: "magiclink",
    email: EMAIL,
  });
  const tokenHash = data?.properties?.hashed_token;
  if (error || !tokenHash) {
    console.error("generateLink failed", error);
    process.exit(1);
  }
  let captured: { name: string; value: string }[] = [];
  const ssr = createServerClient(url, need("NEXT_PUBLIC_SUPABASE_ANON_KEY"), {
    cookies: {
      getAll: () => [],
      setAll: (cs) => {
        captured = cs.map(({ name, value }) => ({ name, value }));
      },
    },
  });
  const { error: vErr } = await ssr.auth.verifyOtp({
    type: "magiclink",
    token_hash: tokenHash,
  });
  if (vErr || captured.length === 0) {
    console.error("verifyOtp failed", vErr);
    process.exit(1);
  }
  return captured.map((c) => `${c.name}=${c.value}`).join("; ");
}

interface RecPick {
  priority?: string;
  model?: string;
  platform?: string;
  engine?: string;
  tier?: string;
  use_frontier?: boolean;
}
interface RecPayload {
  engine?: string;
  tier?: string;
  use_frontier?: boolean;
  recommendations?: RecPick[];
  primary?: string;
}

async function probe(mode: "anon" | "authed", cookie: string, gate: string, bypass: string) {
  const t0 = Date.now();
  const res = await fetch(`${BASE}/api/recommend`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie,
      "X-Roadmodel-Bypass": bypass,
    },
    body: JSON.stringify({ task_description: TASK }),
  });
  const ms = Date.now() - t0;
  const raw = await res.text();
  let payload: RecPayload | null = null;
  try {
    payload = JSON.parse(raw) as RecPayload;
  } catch {
    payload = null;
  }
  console.log(`\n===== ${mode.toUpperCase()} (${res.status}, ${ms}ms) =====`);
  if (!payload) {
    console.log("non-JSON body:", raw.slice(0, 400));
    return;
  }
  // Top-level engine/tier (if the route surfaces them) + per-pick.
  const top = {
    engine: payload.engine,
    tier: payload.tier,
    use_frontier: payload.use_frontier,
    primary: payload.primary,
  };
  console.log("top-level:", JSON.stringify(top));
  const picks = (payload.recommendations ?? []).map((r) => ({
    priority: r.priority,
    model: r.model,
    platform: r.platform,
    engine: r.engine,
    tier: r.tier,
    use_frontier: r.use_frontier,
  }));
  console.log("picks:", JSON.stringify(picks, null, 2));
}

async function main() {
  const gate = `roadmodel_gate=${gateToken(need("SITE_PASSWORD"))}`;
  const bypass = need("ROADMODEL_LATENCY_BYPASS_TOKEN");
  const authCookie = await mintAuthCookie();
  await probe("anon", gate, gate, bypass);
  await probe("authed", `${gate}; ${authCookie}`, gate, bypass);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
