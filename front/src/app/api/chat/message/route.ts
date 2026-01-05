import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const body = await req.json();
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";

  const r = await fetch(`${backendUrl}/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
