import { NextResponse } from "next/server";

export async function GET(req: Request, ctx: { params: Promise<{ jobId: string }> }) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const adminToken = req.headers.get("X-Admin-Token") || "";
  const { jobId } = await ctx.params;

  const headers: Record<string, string> = {};
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const r = await fetch(`${backendUrl}/admin/render-jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
    headers,
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
