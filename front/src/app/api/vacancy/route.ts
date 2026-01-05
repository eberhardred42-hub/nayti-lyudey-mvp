import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const session_id = url.searchParams.get("session_id");

  if (!session_id) {
    return NextResponse.json(
      { error: "session_id is required" },
      { status: 400 }
    );
  }

  const backendUrl = process.env.BACKEND_URL || "http://api:8000";

  try {
    const r = await fetch(`${backendUrl}/vacancy?session_id=${session_id}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    const data = await r.json();
    return NextResponse.json(data, { status: r.status });
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to fetch vacancy data" },
      { status: 500 }
    );
  }
}
