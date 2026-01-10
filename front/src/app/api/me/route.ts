import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const auth = req.headers.get("Authorization") || "";

  const headers: Record<string, string> = {};
  if (auth) headers["Authorization"] = auth;

  let r: Response;
  try {
    r = await fetch(`${backendUrl}/me`, {
      method: "GET",
      headers,
    });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        error: "BACKEND_UNREACHABLE",
        backend_url: backendUrl,
        detail: String(e),
      },
      { status: 502 },
    );
  }

  const raw = await r.text();
  if (!raw) {
    return NextResponse.json(
      {
        ok: false,
        error: "EMPTY_BACKEND_RESPONSE",
        backend_url: backendUrl,
        status: r.status,
      },
      { status: 502 },
    );
  }

  try {
    return NextResponse.json(JSON.parse(raw) as unknown, { status: r.status });
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        error: "NON_JSON_BACKEND_RESPONSE",
        backend_url: backendUrl,
        status: r.status,
        parse_error: String(e),
        body: raw.slice(0, 2000),
      },
      { status: 502 },
    );
  }
}
