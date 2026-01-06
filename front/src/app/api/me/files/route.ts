import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const userId = req.headers.get("X-User-Id") || "";

  const r = await fetch(`${backendUrl}/me/files`, {
    method: "GET",
    headers: {
      "X-User-Id": userId,
    },
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
