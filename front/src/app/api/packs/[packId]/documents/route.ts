import { NextResponse } from "next/server";

export async function GET(req: Request, ctx: { params: Promise<{ packId: string }> }) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const userId = req.headers.get("X-User-Id") || "";
  const { packId } = await ctx.params;

  const r = await fetch(`${backendUrl}/packs/${encodeURIComponent(packId)}/documents`, {
    method: "GET",
    headers: {
      "X-User-Id": userId,
    },
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
