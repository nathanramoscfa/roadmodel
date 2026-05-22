// web/app/(auth)/signout/route.ts

import type { NextResponse } from "next/server";

import { signOut } from "@/lib/auth";

export async function POST(): Promise<NextResponse> {
  return signOut("/");
}
