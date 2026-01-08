"use client";

import { useEffect, useState } from "react";
import { adminMe, adminOverview } from "@/lib/adminApi";
import { maskSensitive } from "@/lib/maskSensitive";

export default function AdminOverviewPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<unknown>(null);
  const [overview, setOverview] = useState<unknown>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [m, o] = await Promise.all([adminMe(), adminOverview()]);
      setMe(m);
      setOverview(o);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить overview");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ maxWidth: 980 }}>
      <div style={{ display: "flex", alignItems: "end", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>Overview</h1>
          <div style={{ marginTop: 6, opacity: 0.7, fontSize: 14 }}>
            Быстрый статус админ-сессии и конфигурации.
          </div>
        </div>
        <button onClick={load} disabled={loading} style={{ border: "1px solid #ddd", borderRadius: 8, padding: "6px 10px" }}>
          {loading ? "Загрузка…" : "Обновить"}
        </button>
      </div>

      {error ? <div style={{ marginTop: 12, color: "crimson" }}>{error}</div> : null}

      <section style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>admin/me</h2>
        <pre style={{ marginTop: 8, background: "#fafafa", border: "1px solid #eee", padding: 12, overflowX: "auto" }}>
          {JSON.stringify(maskSensitive(me), null, 2)}
        </pre>
      </section>

      <section style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>admin/overview</h2>
        <pre style={{ marginTop: 8, background: "#fafafa", border: "1px solid #eee", padding: 12, overflowX: "auto" }}>
          {JSON.stringify(maskSensitive(overview), null, 2)}
        </pre>
      </section>
    </div>
  );
}
