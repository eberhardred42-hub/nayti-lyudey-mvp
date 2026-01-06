"use client";

import { useEffect, useState } from "react";
import { adminAudit } from "@/lib/adminApi";

type AuditItem = {
  id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  before_hash: string | null;
  after_hash: string | null;
  summary: string | null;
  request_id: string | null;
  created_at: string;
};

export default function AdminLogsPage() {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await adminAudit({ limit: 50 });
        if (!cancelled) setItems((data?.items || []) as AuditItem[]);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Ошибка");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>Logs</h1>
      <div style={{ marginTop: 12 }}>Последние admin действия</div>

      {loading && <div style={{ marginTop: 12 }}>Загрузка…</div>}
      {error && <div style={{ marginTop: 12, color: "crimson" }}>{error}</div>}

      {!loading && !items.length && <div style={{ marginTop: 12 }}>Пока пусто.</div>}

      {!!items.length && (
        <div style={{ marginTop: 12, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Когда</th>
                <th style={{ textAlign: "left", padding: 8 }}>Action</th>
                <th style={{ textAlign: "left", padding: 8 }}>Target</th>
                <th style={{ textAlign: "left", padding: 8 }}>Target ID</th>
                <th style={{ textAlign: "left", padding: 8 }}>Before</th>
                <th style={{ textAlign: "left", padding: 8 }}>After</th>
                <th style={{ textAlign: "left", padding: 8 }}>Request</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} style={{ borderTop: "1px solid #eee" }}>
                  <td style={{ padding: 8, whiteSpace: "nowrap" }}>{it.created_at}</td>
                  <td style={{ padding: 8 }}>{it.action}</td>
                  <td style={{ padding: 8 }}>{it.target_type}</td>
                  <td style={{ padding: 8 }}>{it.target_id || ""}</td>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{(it.before_hash || "").slice(0, 10)}</td>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{(it.after_hash || "").slice(0, 10)}</td>
                  <td style={{ padding: 8, fontFamily: "monospace" }}>{(it.request_id || "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
