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

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message || fallback;
  if (typeof e === "string") return e || fallback;
  return fallback;
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

  const [offerAccepted, setOfferAccepted] = useState<boolean | null>(null);
  const [showOfferModal, setShowOfferModal] = useState(false);
  const [offerText, setOfferText] = useState<string | null>(null);
  const [offerLoading, setOfferLoading] = useState(false);
  const [offerCheckbox, setOfferCheckbox] = useState(false);
  const [offerError, setOfferError] = useState<string | null>(null);

  const userId = useMemo(() => (typeof window !== "undefined" ? getOrCreateUserId() : ""), []);

  useEffect(() => {
    let cancelled = false;
    async function loadOfferStatus() {
      try {
        const r = await fetch("/api/legal/offer/status", {
          headers: { "X-User-Id": userId },
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.detail || "Ошибка проверки оферты");
        if (!cancelled) setOfferAccepted(Boolean(data?.accepted));
      } catch {
        // если не получилось проверить, считаем что не принято
        if (!cancelled) setOfferAccepted(false);
      }
    }
    if (userId) loadOfferStatus();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  async function ensureOfferAccepted(): Promise<boolean> {
    if (offerAccepted === true) return true;
    setShowOfferModal(true);
    return false;
  }

  async function loadOfferTextIfNeeded() {
    if (offerText) return;
    setOfferLoading(true);
    setOfferError(null);
    try {
      const r = await fetch("/api/legal/offer", { headers: { "X-User-Id": userId } });
      const text = await r.text();
      if (!r.ok) throw new Error("Не удалось загрузить оферту");
      setOfferText(text);
      sendClientEvent("offer_viewed");
    } catch (e: unknown) {
      setOfferError(errMsg(e, "Ошибка"));
    } finally {
      setOfferLoading(false);
    }
  }

  async function acceptOffer() {
    setOfferError(null);
    sendClientEvent("offer_accept_clicked");
    try {
      const r = await fetch("/api/legal/offer/accept", {
        method: "POST",
        headers: { "X-User-Id": userId },
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.detail || "Ошибка принятия оферты");
      setOfferAccepted(true);
      setShowOfferModal(false);
      setOfferCheckbox(false);
      sendClientEvent("offer_accepted_ok");
    } catch (e: unknown) {
      const msg = errMsg(e, "Ошибка");
      setOfferError(msg);
      sendClientEvent("offer_accept_error", { error: msg });
    }
  }

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

  useEffect(() => {
    let cancelled = false;
    async function loadPacks() {
      setPackLoading(true);
      setPackError(null);
      try {
        const r = await fetch("/api/me/packs", {
          headers: { "X-User-Id": userId },
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки паков");
        const nextPacks: PackItem[] = data.packs || [];
        if (!cancelled) {
          setPacks(nextPacks);
          if (!selectedPackId && nextPacks.length) setSelectedPackId(nextPacks[0].pack_id);
        }
      } catch (e: any) {
        if (!cancelled) setPackError(e?.message || "Ошибка");
      } finally {
        if (!cancelled) setPackLoading(false);
      }
    }
    if (userId) loadPacks();
    return () => {
      cancelled = true;
    };
  }, [userId, selectedPackId]);

  async function refreshPackDocuments(packId: string) {
    if (!packId) return;
    sendClientEvent("ui_render_status_refresh_clicked", { pack_id: packId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/documents`, {
        headers: { "X-User-Id": userId },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка загрузки статусов");
      setPackDocs(data.documents || []);
      sendClientEvent("ui_render_status_opened", { pack_id: packId, docs_count: (data.documents || []).length });
    } catch (e: any) {
      setPackError(e?.message || "Ошибка");
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
    if (!(await ensureOfferAccepted())) return;
    sendClientEvent("ui_render_pack_clicked", { pack_id: packId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/render`, {
        method: "POST",
        headers: { "X-User-Id": userId },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка запуска рендера");
      sendClientEvent("ui_render_pack_ok", { pack_id: packId, jobs_created: data.jobs_created, jobs_skipped: data.jobs_skipped });
      await refreshPackDocuments(packId);
    } catch (e: unknown) {
      const msg = errMsg(e, "Ошибка");
      sendClientEvent("ui_render_pack_fail", { pack_id: packId, error: msg });
      setPackError(msg);
    } finally {
      setPackLoading(false);
    }
  }

  async function regenerateDoc(packId: string, docId: string) {
    if (!(await ensureOfferAccepted())) return;
    sendClientEvent("ui_render_doc_regenerate_clicked", { pack_id: packId, doc_id: docId });
    setPackLoading(true);
    setPackError(null);
    try {
      const r = await fetch(`/api/packs/${encodeURIComponent(packId)}/render/${encodeURIComponent(docId)}`, {
        method: "POST",
        headers: { "X-User-Id": userId },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка регенерации документа");
      sendClientEvent("ui_render_doc_regenerate_ok", { pack_id: packId, doc_id: docId, job_id: data.job_id });
      await refreshPackDocuments(packId);
    } catch (e: unknown) {
      const msg = errMsg(e, "Ошибка");
      sendClientEvent("ui_render_doc_regenerate_fail", { pack_id: packId, doc_id: docId, error: msg });
      setPackError(msg);
    } finally {
      setPackLoading(false);
    }
  }

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
    } catch (e: unknown) {
      const msg = errMsg(e, "Ошибка");
      sendClientEvent("ui_file_download_fail", { file_id: fileId, error: msg });
      setError(msg);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <h1>Библиотека</h1>

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
                            <button disabled={packLoading} onClick={() => download(d.file_id as string)}>
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

      {showOfferModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            zIndex: 50,
          }}
        >
          <div style={{ background: "white", maxWidth: 800, width: "100%", padding: 16, borderRadius: 8 }}>
            <h3 style={{ marginTop: 0 }}>Оферта</h3>
            <p style={{ marginTop: 0 }}>
              Перед генерацией документов нужно прочитать и принять оферту.
            </p>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              <button
                onClick={async () => {
                  await loadOfferTextIfNeeded();
                }}
              >
                Прочитать оферту
              </button>

              <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={offerCheckbox}
                  onChange={(e) => setOfferCheckbox(e.target.checked)}
                />
                <span>Я согласен</span>
              </label>
            </div>

            {offerLoading && <div style={{ marginTop: 12 }}>Загружаю текст…</div>}
            {offerError && <div style={{ marginTop: 12, color: "crimson" }}>{offerError}</div>}

            {offerText && (
              <div
                style={{
                  marginTop: 12,
                  border: "1px solid #ddd",
                  borderRadius: 6,
                  padding: 12,
                  maxHeight: 320,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                  fontSize: 14,
                }}
              >
                {offerText}
              </div>
            )}

            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 16 }}>
              <button
                onClick={() => {
                  setShowOfferModal(false);
                  setOfferCheckbox(false);
                }}
              >
                Закрыть
              </button>
              <button disabled={!offerCheckbox} onClick={acceptOffer}>
                Принять
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
