import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const userId = req.headers.get("X-User-Id") || "";

  const r = await fetch(`${backendUrl}/legal/offer`, {
    method: "GET",
    headers: {
      ...(userId ? { "X-User-Id": userId } : {}),
    },
  });

  const text = await r.text();
  return new NextResponse(text, {
    status: r.status,
    headers: {
      "Content-Type": r.headers.get("content-type") || "text/markdown; charset=utf-8",
    },
  });
}
