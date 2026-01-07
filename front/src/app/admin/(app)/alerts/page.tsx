"use client";

import { useEffect, useState } from "react";
import { adminAlertAck, adminAlertsList } from "@/lib/adminApi";
import { maskSensitive } from "@/lib/maskSensitive";

type AlertItem = {
  id: string;
  severity: string | null;
  event: string | null;
  request_id: string | null;
  ts: string | null;
  context: unknown;
  acked_at: string | null;
  acked_by_user_id: string | null;
  created_at: string;
};

export default function AdminAlertsPage() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severity, setSeverity] = useState("");
  const [event, setEvent] = useState("");
  const [limit, setLimit] = useState(100);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await adminAlertsList({
        limit,
        severity: severity.trim() || undefined,
        event: event.trim() || undefined,
      });
      setItems((data?.items || []) as AlertItem[]);
    } catch (e: any) {
      setError(e?.message || "Ошибка");
    } finally {
      setLoading(false);
    }
  }

  async function ack(id: string) {
    setError(null);
    try {
      await adminAlertAck(id);
      await load();
    } catch (e: any) {
      setError(e?.message || "Ошибка");
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await adminAlertsList({ limit });
        if (!cancelled) setItems((data?.items || []) as AlertItem[]);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Ошибка");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [limit]);

  return (
    <div>
      <h1>Alerts</h1>

      <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>Severity</div>
          <input value={severity} onChange={(e) => setSeverity(e.target.value)} placeholder="warning|error" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>Event</div>
          <input value={event} onChange={(e) => setEvent(e.target.value)} placeholder="bad_config_fallback" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, width: 120 }}>
          <div style={{ fontSize: 12, color: "#555" }}>Limit</div>
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(500, Number(e.target.value || "0"))))}
          />
        </label>
        <button onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      {loading && <div style={{ marginTop: 12 }}>Загрузка…</div>}
      {error && <div style={{ marginTop: 12, color: "crimson" }}>{error}</div>}

      {!loading && !items.length && <div style={{ marginTop: 12 }}>Пока пусто.</div>}

      {!!items.length && (
        <div style={{ marginTop: 12, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 8 }}>Когда</th>
                <th style={{ textAlign: "left", padding: 8 }}>Severity</th>
                <th style={{ textAlign: "left", padding: 8 }}>Event</th>
                <th style={{ textAlign: "left", padding: 8 }}>Request</th>
                <th style={{ textAlign: "left", padding: 8 }}>Ack</th>
                <th style={{ textAlign: "left", padding: 8 }}>Детали</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const isExpanded = expandedId === it.id;
                const when = it.ts || it.created_at;
                const isAcked = !!it.acked_at;

                return (
                  <tr key={it.id} style={{ borderTop: "1px solid #eee" }}>
                    <td style={{ padding: 8, whiteSpace: "nowrap" }}>{when}</td>
                    <td style={{ padding: 8 }}>{it.severity || ""}</td>
                    <td style={{ padding: 8 }}>{it.event || ""}</td>
                    <td style={{ padding: 8, fontFamily: "monospace" }}>{(it.request_id || "").slice(0, 12)}</td>
                    <td style={{ padding: 8, whiteSpace: "nowrap" }}>
                      {isAcked ? (
                        <span>{it.acked_at}</span>
                      ) : (
                        <button onClick={() => ack(it.id)} disabled={loading}>
                          Ack
                        </button>
                      )}
                    </td>
                    <td style={{ padding: 8 }}>
                      <button onClick={() => setExpandedId(isExpanded ? null : it.id)}>
                        {isExpanded ? "Скрыть" : "Показать"}
                      </button>
                      {isExpanded && (
                        <pre
                          style={{
                            marginTop: 8,
                            padding: 12,
                            background: "#fafafa",
                            border: "1px solid #eee",
                            overflowX: "auto",
                            whiteSpace: "pre",
                          }}
                        >
                          {JSON.stringify(
                            maskSensitive({
                              id: it.id,
                              severity: it.severity,
                              event: it.event,
                              ts: it.ts,
                              request_id: it.request_id,
                              context: it.context,
                              acked_at: it.acked_at,
                              acked_by_user_id: it.acked_by_user_id,
                            }),
                            null,
                            2
                          )}
                        </pre>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
