import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const adminToken = req.headers.get("X-Admin-Token") || "";

  const url = new URL(req.url);
  const qs = url.searchParams.toString();

  const headers: Record<string, string> = {};
  if (adminToken) headers["X-Admin-Token"] = adminToken;

  const r = await fetch(`${backendUrl}/admin/render-jobs${qs ? `?${qs}` : ""}`, {
    method: "GET",
    headers,
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
