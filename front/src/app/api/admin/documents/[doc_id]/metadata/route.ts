import { NextResponse } from "next/server";

export async function POST(req: Request, ctx: { params: Promise<{ doc_id: string }> }) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const adminToken = req.headers.get("X-Admin-Token") || "";
  const { doc_id } = await ctx.params;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const body = await req.text();
  const r = await fetch(`${backendUrl}/admin/documents/${encodeURIComponent(doc_id)}/metadata`, {
    method: "POST",
    headers,
    body,
  });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
