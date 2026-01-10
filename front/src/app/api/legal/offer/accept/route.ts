import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const auth = req.headers.get("Authorization") || "";

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) headers["Authorization"] = auth;

  const r = await fetch(`${backendUrl}/legal/offer/accept`, {
    method: "POST",
    headers,
    body: JSON.stringify({}),
  });

  const data = await r.json().catch(() => ({}));
  return NextResponse.json(data, { status: r.status });
}
