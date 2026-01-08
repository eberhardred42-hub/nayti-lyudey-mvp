import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const auth = req.headers.get("Authorization") || "";
  const userId = req.headers.get("X-User-Id") || "";

  const headers: Record<string, string> = {};
  if (auth) headers["Authorization"] = auth;
  else if (userId) headers["X-User-Id"] = userId;

  const r = await fetch(`${backendUrl}/me/packs`, {
    method: "GET",
    headers,
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
