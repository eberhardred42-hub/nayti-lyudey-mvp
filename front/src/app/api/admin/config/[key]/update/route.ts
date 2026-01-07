import { NextResponse } from "next/server";

export async function POST(req: Request, ctx: { params: Promise<{ key: string }> }) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const adminToken = req.headers.get("X-Admin-Token") || "";
  const { key } = await ctx.params;

  const body = await req.text();

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const r = await fetch(`${backendUrl}/admin/config/${encodeURIComponent(key)}/update`, {
    method: "POST",
    headers,
    body,
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
