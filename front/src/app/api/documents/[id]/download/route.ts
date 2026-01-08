export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;

  const backendUrl = process.env.BACKEND_URL || "http://api:8000";
  const auth = req.headers.get("Authorization") || "";
  const userId = req.headers.get("X-User-Id") || "";

  const headers: Record<string, string> = {};
  if (auth) headers["Authorization"] = auth;
  else if (userId) headers["X-User-Id"] = userId;

  const r = await fetch(`${backendUrl}/documents/${encodeURIComponent(id)}/download`, {
    method: "GET",
    headers,
  });

  // Проксируем поток как есть (PDF может быть большим)
  return new Response(r.body, {
    status: r.status,
    headers: {
      "Content-Type": r.headers.get("content-type") || "application/pdf",
      "Content-Disposition": r.headers.get("content-disposition") || "attachment",
      "Cache-Control": "no-store",
    },
  });
}
