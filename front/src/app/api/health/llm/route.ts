import { NextResponse } from "next/server";

export async function GET() {
  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const r = await fetch(`${backendUrl}/health/llm`, { method: "GET" });
  const data = await r.json();
  return NextResponse.json(data, { status: r.status });
}
