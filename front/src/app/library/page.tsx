"use client";

import { useEffect, useMemo, useState } from "react";

type FileItem = {
  file_id: string;
  artifact_id: string;
  kind: string | null;
  created_at: string | null;
  content_type: string | null;
  size_bytes: number | null;
  doc_id: string | null;
  status: string;
};

function getOrCreateUserId(): string {
  const key = "nly_user_id";
  const existing = typeof window !== "undefined" ? window.localStorage.getItem(key) : null;
  if (existing) return existing;
  const id = crypto.randomUUID();
  window.localStorage.setItem(key, id);
  return id;
}

async function sendClientEvent(event: string, props?: Record<string, unknown>) {
  try {
    await fetch("/api/events/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, props }),
    });
  } catch {
    // ignore
  }
}

export default function LibraryPage() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const userId = useMemo(() => (typeof window !== "undefined" ? getOrCreateUserId() : ""), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch("/api/me/files", {
          headers: { "X-User-Id": userId },
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки");
        if (!cancelled) {
          setFiles(data.files || []);
          sendClientEvent("ui_library_files_opened", { files_count: (data.files || []).length });
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Ошибка");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (userId) load();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  async function download(fileId: string) {
    sendClientEvent("ui_file_download_clicked", { file_id: fileId });
    try {
      const r = await fetch(`/api/files/${fileId}/download`, {
        headers: { "X-User-Id": userId },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка скачивания");
      sendClientEvent("ui_file_download_ok", { file_id: fileId });
      if (data?.url) {
        window.location.href = data.url;
      }
    } catch (e: any) {
      sendClientEvent("ui_file_download_fail", { file_id: fileId, error: e?.message || "error" });
      setError(e?.message || "Ошибка");
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <h1>Библиотека</h1>

      <section style={{ marginTop: 24 }}>
        <h2>Файлы</h2>

        {loading && <div>Загрузка…</div>}
        {error && <div style={{ color: "crimson" }}>{error}</div>}

        {!loading && !files.length && <div>Пока файлов нет.</div>}

        {!!files.length && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: 8 }}>Тип</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Создан</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Размер</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Doc ID</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Действие</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f) => (
                  <tr key={f.file_id}>
                    <td style={{ padding: 8 }}>{f.kind || "—"}</td>
                    <td style={{ padding: 8 }}>{f.created_at || "—"}</td>
                    <td style={{ padding: 8 }}>{typeof f.size_bytes === "number" ? f.size_bytes : "—"}</td>
                    <td style={{ padding: 8 }}>{f.doc_id || "—"}</td>
                    <td style={{ padding: 8 }}>
                      <button onClick={() => download(f.file_id)}>Скачать</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
