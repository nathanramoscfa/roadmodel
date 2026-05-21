// web/app/api/gate/route.ts
import { NextRequest, NextResponse } from "next/server";
import { GATE_COOKIE, deriveGateToken } from "@/lib/gate";

const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7; // 7 days

function safeNext(raw: string | null): string {
  if (typeof raw !== "string" || raw.length === 0) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const expected = process.env.SITE_PASSWORD;
  if (!expected) {
    return NextResponse.redirect(new URL("/", req.url), 303);
  }

  const form = await req.formData();
  const submitted = form.get("password");
  const next = safeNext(
    typeof form.get("next") === "string"
      ? (form.get("next") as string)
      : null,
  );

  if (typeof submitted !== "string" || submitted !== expected) {
    const url = new URL("/gate", req.url);
    url.searchParams.set("next", next);
    url.searchParams.set("error", "1");
    return NextResponse.redirect(url, 303);
  }

  const token = await deriveGateToken(expected);
  const response = NextResponse.redirect(new URL(next, req.url), 303);
  response.cookies.set({
    name: GATE_COOKIE,
    value: token,
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}
