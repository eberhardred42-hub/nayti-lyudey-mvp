import { NextResponse } from "next/server";

export async function POST(req: Request, ctx: { params: Promise<{ key: string }> }) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const adminToken = req.headers.get("X-Admin-Token") || "";
  const { key } = await ctx.params;

  const headers: Record<string, string> = {};
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const r = await fetch(`${backendUrl}/admin/config/${encodeURIComponent(key)}/draft`, {
    method: "POST",
    headers,
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
