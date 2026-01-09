"use client";

import { useEffect, useState } from "react";
import { adminLogs } from "@/lib/adminApi";
import { maskSensitive } from "@/lib/maskSensitive";

type LogItem = {
  source: string;
  id: string;
  kind: string;
  created_at: string;
  payload_json: any;
  meta: any;
  session_id: string | null;
};

export default function AdminLogsPage() {
  const [items, setItems] = useState<LogItem[]>([]);
  const [llmBadge, setLlmBadge] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("");
  const [packId, setPackId] = useState("");
  const [docId, setDocId] = useState("");
  const [status, setStatus] = useState("");
  const [limit, setLimit] = useState(200);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await adminLogs({
        kind: kind.trim() || undefined,
        pack_id: packId.trim() || undefined,
        doc_id: docId.trim() || undefined,
        status: status.trim() || undefined,
        limit,
      });
      setItems((data?.items || []) as LogItem[]);
    } catch (e: any) {
      setError(e?.message || "Ошибка");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await adminLogs({ limit });
        if (!cancelled) setItems((data?.items || []) as LogItem[]);
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
  }, [limit]);

  useEffect(() => {
    let cancelled = false;
    async function loadLlmInfo() {
      try {
        const r = await fetch("/api/health/llm", { method: "GET" });
        const j = await r.json();
        const provider = String(j?.provider || "");
        const model = String(j?.model || "");
        if (!cancelled) setLlmBadge(provider && model ? `LLM: ${provider}/${model}` : provider ? `LLM: ${provider}` : "");
      } catch {
        if (!cancelled) setLlmBadge("");
      }
    }
    loadLlmInfo();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>Logs</h1>

      {!!llmBadge && <div style={{ marginTop: 6, fontSize: 12, color: "#555" }}>{llmBadge}</div>}

      <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>Kind</div>
          <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="например, alert_event" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>pack_id</div>
          <input value={packId} onChange={(e) => setPackId(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>doc_id</div>
          <input value={docId} onChange={(e) => setDocId(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, color: "#555" }}>status (для render_job)</div>
          <input value={status} onChange={(e) => setStatus(e.target.value)} placeholder="queued|rendering|failed|done" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, width: 120 }}>
          <div style={{ fontSize: 12, color: "#555" }}>Limit</div>
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(1000, Number(e.target.value || "0"))))}
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
                <th style={{ textAlign: "left", padding: 8 }}>Source</th>
                <th style={{ textAlign: "left", padding: 8 }}>Kind</th>
                <th style={{ textAlign: "left", padding: 8 }}>ID</th>
                <th style={{ textAlign: "left", padding: 8 }}>Session</th>
                <th style={{ textAlign: "left", padding: 8 }}>Детали</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const isExpanded = expandedId === it.id;
                return (
                  <tr key={it.id} style={{ borderTop: "1px solid #eee" }}>
                    <td style={{ padding: 8, whiteSpace: "nowrap" }}>{it.created_at}</td>
                    <td style={{ padding: 8 }}>{it.source}</td>
                    <td style={{ padding: 8 }}>{it.kind}</td>
                    <td style={{ padding: 8, fontFamily: "monospace" }}>{it.id.slice(0, 12)}</td>
                    <td style={{ padding: 8, fontFamily: "monospace" }}>{(it.session_id || "").slice(0, 12)}</td>
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
                            maskSensitive({ payload_json: it.payload_json, meta: it.meta }),
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
