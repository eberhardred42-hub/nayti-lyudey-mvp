import { NextResponse } from "next/server";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ packId: string; docId: string }> }
) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const auth = req.headers.get("Authorization") || "";
  const userId = req.headers.get("X-User-Id") || "";
  const { packId, docId } = await ctx.params;

  const headers: Record<string, string> = {};
  if (auth) headers["Authorization"] = auth;
  else if (userId) headers["X-User-Id"] = userId;

  const r = await fetch(
    `${backendUrl}/packs/${encodeURIComponent(packId)}/render/${encodeURIComponent(docId)}`,
    {
      method: "POST",
      headers,
    }
  );

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
