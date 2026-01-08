import { NextResponse } from "next/server";

export async function POST(req: Request) {
  let body: unknown = null;
  try {
    body = await req.json();
  } catch {
    body = null;
  }

  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const auth = req.headers.get("Authorization") || "";
  const userId = req.headers.get("X-User-Id") || "";

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) headers["Authorization"] = auth;
  else if (userId) headers["X-User-Id"] = userId;

  let r: Response;
  try {
    r = await fetch(`${backendUrl}/documents/generate_pack`, {
      method: "POST",
      headers,
      body: JSON.stringify(body ?? {}),
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

  // Бэкенд по контракту отдаёт JSON. Если вернул не-JSON — отдаём 502 с диагностикой.
  try {
    const data = JSON.parse(raw) as unknown;
    return NextResponse.json(data, { status: r.status });
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
