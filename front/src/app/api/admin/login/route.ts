import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const userId = req.headers.get("X-User-Id") || "";
  const auth = req.headers.get("Authorization") || "";
  const body = await req.json();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (userId) headers["X-User-Id"] = userId;
  if (auth) headers["Authorization"] = auth;

  const r = await fetch(`${backendUrl}/admin/login`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
