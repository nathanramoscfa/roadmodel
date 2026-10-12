import { NextResponse } from "next/server";
import { signOut } from "@/lib/auth";
import { privateRoute, sameOrigin } from "@/lib/http-boundaries";

export const POST = privateRoute(async (req: Request): Promise<Response> => {
  if (!sameOrigin(req)) return NextResponse.json({ error: "cross_origin" }, { status: 403 });
  return signOut("/", new URL(req.url).origin);
});
