// web/app/api/test/e2e-reset/route.ts
import { NextResponse } from "next/server";

import { e2eClearProfiles, isE2eAuthEnabled } from "@/lib/profile";

export async function POST(): Promise<Response> {
  if (!isE2eAuthEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  e2eClearProfiles();
  return NextResponse.json({ ok: true });
}
