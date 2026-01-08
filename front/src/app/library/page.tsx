"use client";

import { useEffect, useMemo, useState } from "react";
import { UserAuthHeader } from "@/components/UserAuthHeader";
import { getUserToken } from "@/lib/userSession";

function getErrorMessage(e: unknown, fallback: string) {
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

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

type PackItem = {
  pack_id: string;
  session_id: string;
  created_at: string | null;
};

type PackDocumentItem = {
  doc_id: string;
  title: string;
  status: string;
  file_id: string | null;
  attempts: number;
  last_error: string | null;
  access?: {
    tier: string;
    enabled: boolean;
    is_locked: boolean;
    reason: string | null;
  };
};

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
  const [packs, setPacks] = useState<PackItem[]>([]);
  const [selectedPackId, setSelectedPackId] = useState<string>("");
  const [packDocs, setPackDocs] = useState<PackDocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [packLoading, setPackLoading] = useState(false);
  const [packError, setPackError] = useState<string | null>(null);

  const [token, setToken] = useState<string | null>(
    useMemo(() => (typeof window !== "undefined" ? getUserToken() : null), [])
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setToken(getUserToken());
    window.addEventListener("storage", sync);
    window.addEventListener("nly-auth-changed", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("nly-auth-changed", sync);
    };
  }, []);

  const authHeaders = useMemo(() => {
    if (!token) return null;
    return { Authorization: token.toLowerCase().startsWith("bearer ") ? token : `Bearer ${token}` };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch("/api/me/files", {
          headers: authHeaders || undefined,
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки");
        if (!cancelled) {
          setFiles(data.files || []);
          sendClientEvent("ui_library_files_opened", { files_count: (data.files || []).length });
        }
      } catch (e: unknown) {
        if (!cancelled) setError(getErrorMessage(e, "Ошибка"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (!authHeaders) {
      setFiles([]);
      return;
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [authHeaders]);

  useEffect(() => {
    let cancelled = false;
    async function loadPacks() {
      setPackLoading(true);
      setPackError(null);
      try {
        const r = await fetch("/api/me/packs", {
          headers: authHeaders || undefined,
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки паков");
        const nextPacks: PackItem[] = data.packs || [];
        if (!cancelled) {
          setPacks(nextPacks);
          if (!selectedPackId && nextPacks.length) setSelectedPackId(nextPacks[0].pack_id);
        }
      } catch (e: unknown) {
        if (!cancelled) setPackError(getErrorMessage(e, "Ошибка"));
      } finally {
        if (!cancelled) setPackLoading(false);
      }
    }
    if (!authHeaders) {
      setPacks([]);
      setSelectedPackId("");
      setPackDocs([]);
      return;
    }
    loadPacks();
    return () => {
      cancelled = true;
    };
  }, [authHeaders, selectedPackId]);

  async function refreshPackDocuments(packId: string) {
    if (!packId) return;
    if (!authHeaders) return;
    sendClientEvent("ui_render_status_refresh_clicked", { pack_id: packId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/documents`, {
        headers: authHeaders,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки статусов");
      setPackDocs(data.documents || []);
      sendClientEvent("ui_render_status_opened", { pack_id: packId, docs_count: (data.documents || []).length });
    } catch (e: unknown) {
      setPackError(getErrorMessage(e, "Ошибка"));
    } finally {
      setPackLoading(false);
    }
  }

  useEffect(() => {
    if (!selectedPackId) {
      setPackDocs([]);
      return;
    }
    refreshPackDocuments(selectedPackId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPackId]);

  async function renderPack(packId: string) {
    if (!packId) return;
    if (!authHeaders) return;
    sendClientEvent("ui_render_pack_clicked", { pack_id: packId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/render`, {
        method: "POST",
        headers: authHeaders,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка запуска рендера");
      sendClientEvent("ui_render_pack_ok", { pack_id: packId, jobs_created: data.jobs_created, jobs_skipped: data.jobs_skipped });
      await refreshPackDocuments(packId);
    } catch (e: unknown) {
      sendClientEvent("ui_render_pack_fail", { pack_id: packId, error: getErrorMessage(e, "error") });
      setPackError(getErrorMessage(e, "Ошибка"));
    } finally {
      setPackLoading(false);
    }
  }

  async function regenerateDoc(packId: string, docId: string) {
    sendClientEvent("ui_render_doc_regenerate_clicked", { pack_id: packId, doc_id: docId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/render/${encodeURIComponent(docId)}`, {
        method: "POST",
        headers: authHeaders || undefined,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка регенерации документа");
      sendClientEvent("ui_render_doc_regenerate_ok", { pack_id: packId, doc_id: docId, job_id: data.job_id });
      await refreshPackDocuments(packId);
    } catch (e: unknown) {
      sendClientEvent("ui_render_doc_regenerate_fail", { pack_id: packId, doc_id: docId, error: getErrorMessage(e, "error") });
      setPackError(getErrorMessage(e, "Ошибка"));
    } finally {
      setPackLoading(false);
    }
  }

  async function download(fileId: string) {
    sendClientEvent("ui_file_download_clicked", { file_id: fileId });
    try {
      const r = await fetch(`/api/files/${fileId}/download`, {
        headers: authHeaders || undefined,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка скачивания");
      sendClientEvent("ui_file_download_ok", { file_id: fileId });
      if (data?.url) {
        window.location.href = data.url;
      }
    } catch (e: unknown) {
      sendClientEvent("ui_file_download_fail", { file_id: fileId, error: getErrorMessage(e, "error") });
      setError(getErrorMessage(e, "Ошибка"));
    }
  }

  return (
    <main style={{ padding: 0, maxWidth: 960, margin: "0 auto" }}>
      <UserAuthHeader title="Библиотека" />

      {!authHeaders ? (
        <section style={{ padding: 24 }}>
          <div>Чтобы открыть библиотеку, нужно войти.</div>
          <button
            style={{ marginTop: 12 }}
            onClick={() => {
              if (typeof window === "undefined") return;
              window.dispatchEvent(new Event("nly-open-login"));
            }}
          >
            Войти
          </button>
        </section>
      ) : (
        <section style={{ padding: 24 }}>
          <section style={{ marginTop: 24 }}>
            <h2>Пак документов</h2>

        {packLoading && <div>Загрузка…</div>}
        {packError && <div style={{ color: "crimson" }}>{packError}</div>}

        {!packLoading && !packs.length && <div>Пока паков нет.</div>}

        {!!packs.length && (
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <label>
              Pack:
              <select
                value={selectedPackId}
                onChange={(e) => setSelectedPackId(e.target.value)}
                style={{ marginLeft: 8 }}
              >
                {packs.map((p) => (
                  <option key={p.pack_id} value={p.pack_id}>
                    {p.pack_id}
                  </option>
                ))}
              </select>
            </label>

            <button disabled={!selectedPackId || packLoading} onClick={() => renderPack(selectedPackId)}>
              Сгенерировать весь пак
            </button>

            <button disabled={!selectedPackId || packLoading} onClick={() => refreshPackDocuments(selectedPackId)}>
              Обновить статусы
            </button>
          </div>
        )}

        {!!selectedPackId && !!packDocs.length && (
          <div style={{ overflowX: "auto", marginTop: 12 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: 8 }}>Doc</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Статус</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Файл</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Действия</th>
                </tr>
              </thead>
              <tbody>
                {packDocs.map((d) => (
                  <tr key={d.doc_id}>
                    <td style={{ padding: 8 }}>
                      <div>{d.title}</div>
                      <div style={{ opacity: 0.7, fontSize: 12 }}>{d.doc_id}</div>
                      {d.access?.is_locked ? (
                        <div style={{ marginTop: 4, color: "crimson", fontSize: 12 }}>
                          Locked: {d.access.tier}
                          {d.access.reason ? ` (${d.access.reason})` : ""}
                        </div>
                      ) : null}
                    </td>
                    <td style={{ padding: 8 }}>{d.status}</td>
                    <td style={{ padding: 8 }}>{d.file_id ? d.file_id : "—"}</td>
                    <td style={{ padding: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {d.access?.is_locked ? (
                        <span style={{ opacity: 0.7 }}>Недоступно</span>
                      ) : (
                        <>
                          <button disabled={packLoading} onClick={() => regenerateDoc(selectedPackId, d.doc_id)}>
                            Пересобрать
                          </button>
                          {d.file_id && (
                            <button disabled={packLoading} onClick={() => download(String(d.file_id))}>
                              Скачать
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
          </section>

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
        </section>
      )}
    </main>
  );
}
