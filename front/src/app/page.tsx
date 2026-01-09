"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./page.module.css";
import { clearUserSession, getOrCreateUserId, getUserToken } from "@/lib/userSession";
import { UserLoginModal } from "@/components/UserLoginModal";

type Msg = { role: "user" | "assistant"; text: string };

type Stage =
  | "start"
  | "choose_flow"
  | "vacancy_text"
  | "tasks"
  | "clarifications"
  | "free_result";

type FreeReport = {
  headline: string;
  where_to_search: Array<{ title: string; bullets: string[] }>;
  what_to_screen: string[];
  budget_reality_check: {
    status: string;
    bullets: string[];
  };
  next_steps: string[];
};

const CLARIFICATIONS = [
  "Город и формат (удалённо / очно)",
  "Бюджет (примерно)",
  "Занятость (полная / частичная / по задачам)",
];

export default function Page() {
  const [profession, setProfession] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [stage, setStage] = useState<Stage>("start");
  const [clarIdx, setClarIdx] = useState(0);
  const [clarAnswers, setClarAnswers] = useState<string[]>([]);
  const [showPayModal, setShowPayModal] = useState(false);
  const [freeReport, setFreeReport] = useState<FreeReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);
  const [userToken, setUserTokenState] = useState<string | null>(null);
  const [autoDoc, setAutoDoc] = useState<{ id: string; title: string; status: string } | null>(null);
  const [autoGenStarted, setAutoGenStarted] = useState(false);
  const [pdfDocs, setPdfDocs] = useState<Array<{ id: string; doc_id: string; title: string; status: string }>>([]);

  const boxRef = useRef<HTMLDivElement | null>(null);

  function statusLabel(status: string): string {
    const s = (status || "").trim();
    if (!s || s === "ready") return "";
    if (s === "pending") return "в работе";
    if (s === "error") return "ошибка";
    if (s === "needs_input") return "нужны данные";
    return "";
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setUserTokenState(getUserToken());
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener("nly-auth-changed", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("nly-auth-changed", sync);
    };
  }, []);
  
  // Mode: "search" or "chat"
  const mode = stage === "start" ? "search" : "chat";

  async function readJsonSafe(resp: Response): Promise<unknown | null> {
    const raw = await resp.text();
    if (!raw) return null;
    try {
      return JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }

  function authHeaders(): Record<string, string> {
    const token = getUserToken();
    if (token) return { Authorization: token.startsWith("Bearer ") ? token : `Bearer ${token}` };
    const userId = getOrCreateUserId();
    return userId ? { "X-User-Id": userId } : {};
  }

  async function refreshMeDocuments(): Promise<Array<{ id: string; doc_id: string; title: string; status: string }>> {
    try {
      const r = await fetch("/api/me/documents", {
        method: "GET",
        headers: authHeaders(),
        credentials: "include",
        cache: "no-store",
      });
      const data = await readJsonSafe(r);
      if (!data || typeof data !== "object") return [];
      const dataObj = data as Record<string, unknown>;
      const docs: unknown[] = Array.isArray(dataObj.documents) ? (dataObj.documents as unknown[]) : [];
      const pdf = docs
        .map((v) => {
          if (!v || typeof v !== "object") return null;
          const o = v as Record<string, unknown>;
          if (o.type !== "pdf") return null;
          const id = typeof o.id === "string" ? o.id : "";
          if (!id) return null;
          const doc_id = typeof o.doc_id === "string" ? o.doc_id : "";
          const title = typeof o.title === "string" ? o.title : "Документ";
          const status = typeof o.status === "string" ? o.status : "";
          return { id, doc_id, title, status };
        })
        .filter(Boolean) as Array<{ id: string; doc_id: string; title: string; status: string }>;
      setPdfDocs(pdf);
      return pdf;
    } catch {
      // ignore
      return [];
    }
  }

  async function ensureAutoDocumentGenerated(sid: string) {
    if (!sid) return;
    if (autoGenStarted) return;
    setAutoGenStarted(true);
    try {
      const genR = await fetch("/api/documents/generate_pack", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sid }),
      });

      if (!genR.ok) {
        pushAssistantOnce("Не удалось запустить генерацию пакета документов. Попробуй позже.");
        return;
      }

      const docsNow = await refreshMeDocuments();
      const candidate = docsNow.find((d) => d.doc_id === "candidate_onepager") || null;
      if (candidate) {
        setAutoDoc({ id: candidate.id, title: candidate.title, status: candidate.status });
        if (candidate.status === "ready") {
          pushAssistantOnce(`Документ «${candidate.title}» готов. Нажми «Скачать».`);
        }
      }
    } catch {
      pushAssistantOnce("Не удалось запустить генерацию пакета документов. Попробуй позже.");
    }
  }

  async function downloadDocument(documentId: string, title: string) {
    if (!documentId) return;
    const r = await fetch(`/api/documents/${documentId}/download`, {
      method: "GET",
      headers: authHeaders(),
      credentials: "include",
    });
    if (!r.ok) {
      pushAssistantOnce("Не удалось скачать документ. Попробуй ещё раз.");
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title || "document"}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Автоскролл вниз при новых сообщениях
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, stage, freeReport]);

  // Периодически подтягиваем список документов, чтобы PDF появлялись без перезагрузки
  useEffect(() => {
    if (!sessionId) return;
    if (mode !== "chat") return;

    let alive = true;
    const tick = async () => {
      if (!alive) return;
      await refreshMeDocuments();
    };

    // сразу и затем по таймеру
    void tick();
    const t = window.setInterval(() => {
      void tick();
    }, 15000);

    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [sessionId, mode, userToken]);

  async function start() {
    if (!profession.trim()) return;
    setAutoDoc(null);
    setAutoGenStarted(false);
    try {
      const r = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ profession_query: profession.trim() }),
      });

      const data = await readJsonSafe(r);
      const dataObj = data && typeof data === "object" ? (data as Record<string, unknown>) : null;
      const sid = typeof dataObj?.session_id === "string" ? dataObj.session_id : "";
      if (!sid) throw new Error("no_session_id");
      setSessionId(sid);

      // immediately call backend chat start
      const resp = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sid, type: "intro_start" }),
      });
      const body = await readJsonSafe(resp);
      const bodyObj = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
      const reply = typeof bodyObj?.reply === "string" ? bodyObj.reply : "";
      const qrs = Array.isArray(bodyObj?.quick_replies) ? (bodyObj?.quick_replies as unknown[]) : [];
      const readyToSearch = Boolean(bodyObj?.ready_to_search);
      const documentsReady = Boolean(bodyObj?.documents_ready);

      if (reply) setMessages([{ role: "assistant", text: reply }]);
      setQuickReplies(qrs.map(String).filter(Boolean));

      if (readyToSearch || documentsReady) {
        await ensureAutoDocumentGenerated(String(sid));
        await refreshMeDocuments();
      }
      if (qrs.length) setStage("choose_flow");
    } catch {
      setMessages([{ role: "assistant", text: "Сервис временно недоступен. Попробуй ещё раз." }]);
      setQuickReplies([]);
      setStage("choose_flow");
      await refreshMeDocuments();
    }
  }

  function pushAssistantOnce(text: string) {
    setMessages((m) => [...m, { role: "assistant", text }]);
  }

  async function fetchFreeReport(sid: string) {
    if (!sid) return;
    setReportLoading(true);
    setReportError(null);
    try {
      const r = await fetch(`/api/report/free?session_id=${sid}`, { credentials: "include" });
      const data = await readJsonSafe(r);
      const dataObj = data && typeof data === "object" ? (data as Record<string, unknown>) : null;
      if (r.ok && dataObj?.free_report && typeof dataObj.free_report === "object") {
        setFreeReport(dataObj.free_report as FreeReport);
      } else {
        setReportError("Не удалось загрузить отчёт, попробуй обновить");
      }
    } catch (err) {
      setReportError("Ошибка при загрузке отчёта");
    } finally {
      setReportLoading(false);
    }
  }

  async function sendToChat(text: string) {
    if (!sessionId) return;
    try {
      const r = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sessionId, type: "intro_message", text }),
      });
      const data = await readJsonSafe(r);
      const dataObj = data && typeof data === "object" ? (data as Record<string, unknown>) : null;
      const reply = typeof dataObj?.reply === "string" ? dataObj.reply : "";
      const qrs = Array.isArray(dataObj?.quick_replies) ? (dataObj.quick_replies as unknown[]) : [];
      const readyToSearch = Boolean(dataObj?.ready_to_search);
      const documentsReady = Boolean(dataObj?.documents_ready);

      if (reply) setMessages((m) => [...m, { role: "assistant", text: reply }]);
      setQuickReplies(qrs.map(String).filter(Boolean));

      if ((readyToSearch || documentsReady) && sessionId) {
        await ensureAutoDocumentGenerated(sessionId);
        await refreshMeDocuments();
      }
    } catch {
      pushAssistantOnce("Сервис временно недоступен. Попробуй ещё раз.");
    }
  }

  function handleChoose(hasVacancy: boolean) {
    const text = hasVacancy ? "Есть текст вакансии" : "Нет вакансии, есть задачи";
    setMessages((m) => [...m, { role: "user", text }]);
    sendToChat(text);
  }

  function startClarifications() {
    setStage("clarifications");
    setClarIdx(0);
    setClarAnswers([]);
    pushAssistantOnce(`Нужно уточнить: ${CLARIFICATIONS[0]}`);
  }

  function handleUserSend(text: string) {
    if (!text.trim()) return;
    const trimmed = text.trim();
    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setInput("");
    sendToChat(trimmed);
  }

  return (
    <div className={styles.container}>
      <div className={styles.topRightActions}>
        <button
          className={styles.iconCircleBtn}
          aria-label={userToken ? "Выйти" : "Войти"}
          onClick={() => {
            if (userToken) {
              clearUserSession();
              setUserTokenState(null);
              return;
            }
            setLoginOpen(true);
          }}
        >
          {userToken ? "⎋" : "⎆"}
        </button>
        <button
          className={styles.iconCircleBtn}
          aria-label="Помощь"
          onClick={() => {
            if (typeof window === "undefined") return;
            window.location.href = "/library";
          }}
        >
          ?
        </button>
      </div>

      <UserLoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onLoggedIn={() => {
          setUserTokenState(getUserToken());
        }}
      />
      {mode === "search" ? (
        // Стартовый экран: пустая страница, только строка ввода
        <div className={styles.searchMode}>
          <div className={styles.searchBox}>
            <input
              className={styles.searchInput}
              value={profession}
              onChange={(e) => setProfession(e.target.value)}
              placeholder="Кого ты ищешь?"
              onKeyDown={(e) => {
                if (e.key === "Enter" && profession.trim()) {
                  start();
                }
              }}
            />
            <button className={styles.searchBtn} onClick={start} disabled={!profession.trim()}>
              Найти людей
            </button>
          </div>
        </div>
      ) : (
        // Чат-экран: топ запрос + сообщения + composer
        <div className={styles.chatMode}>
          {/* Запрос наверху (sticky) */}
          <div className={styles.topQuery}>
            <div className={styles.topQueryLabel}>Запрос</div>
            <div className={styles.topQueryText}>{profession}</div>
          </div>

          {/* Область сообщений */}
          <div className={styles.messagesArea} ref={boxRef}>
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? `${styles.message} ${styles.messageUser}`
                    : `${styles.message} ${styles.messageAssistant}`
                }
              >
                {m.text}
              </div>
            ))}

            {/* Free report */}
            {stage === "free_result" && (
              <div className={styles.freeReportBox}>
                {reportLoading && (
                  <div className={styles.reportLoading}>Загружаю отчёт...</div>
                )}

                {reportError && (
                  <div className={styles.reportError}>{reportError}</div>
                )}

                {freeReport && (
                  <>
                    <h3>{freeReport.headline}</h3>

                    {/* Где искать */}
                    <div>
                      <h4>Где искать</h4>
                      {freeReport.where_to_search.map((section, idx) => (
                        <div key={idx}>
                          <div style={{ fontWeight: "bold", marginBottom: 4 }}>
                            {section.title}
                          </div>
                          <ul>
                            {section.bullets.map((bullet, bidx) => (
                              <li key={bidx}>{bullet}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>

                    {/* На что смотреть */}
                    <div>
                      <h4>На что смотреть</h4>
                      <ul>
                        {freeReport.what_to_screen.map((item, idx) => (
                          <li key={idx}>{item}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Бюджет: реальность */}
                    <div>
                      <h4>Бюджет: реальность</h4>
                      <ul>
                        {freeReport.budget_reality_check.bullets.map((bullet, idx) => (
                          <li key={idx}>{bullet}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Дальше */}
                    <div>
                      <h4>Дальше</h4>
                      <ol>
                        {freeReport.next_steps.map((step, idx) => (
                          <li key={idx}>{step}</li>
                        ))}
                      </ol>
                    </div>

                    <button
                      className={styles.fullPackageBtn}
                      onClick={() => setShowPayModal(true)}
                    >
                      Получить полный пакет
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Auto-generated first document */}
            {autoDoc?.status === "ready" && (
              <div className={styles.freeReportBox}>
                <h4>Документ готов</h4>
                <div>{autoDoc.title}</div>
                <button
                  className={styles.fullPackageBtn}
                  onClick={() => downloadDocument(autoDoc.id, autoDoc.title)}
                >
                  Скачать
                </button>
              </div>
            )}

            {/* List of PDF documents */}
            {pdfDocs.length > 0 && (
              <div className={styles.freeReportBox}>
                <h4>Твои документы</h4>
                {pdfDocs.map((d) => (
                  <div key={d.id} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                    <div style={{ flex: 1 }}>
                      {d.title}
                      {statusLabel(d.status) ? ` (${statusLabel(d.status)})` : ""}
                    </div>
                    {d.status === "ready" && (
                      <button className={styles.fullPackageBtn} onClick={() => downloadDocument(d.id, d.title)}>
                        Скачать
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Composer внизу */}
          <div className={styles.composerArea}>
            <div className={styles.composerRow}>
              <input
                className={styles.composerInput}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
                  stage === "vacancy_text"
                    ? "Вставь текст вакансии..."
                    : stage === "tasks"
                    ? "Опиши задачи..."
                    : stage === "clarifications"
                    ? `Ответ: ${CLARIFICATIONS[clarIdx] ?? "..."}`
                    : "Напиши сообщение..."
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" && input.trim()) {
                    handleUserSend(input);
                  }
                }}
              />
              <button className={styles.sendBtn} onClick={() => handleUserSend(input)}>
                Отправить
              </button>
            </div>

            {/* Quick replies */}
            {quickReplies.length > 0 && (
              <div className={styles.quickReplies}>
                {quickReplies.map((q, idx) => (
                  <button
                    key={idx}
                    className={styles.quickReplyBtn}
                    onClick={() => {
                      setMessages((m) => [...m, { role: "user", text: q }]);
                      sendToChat(q);
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Paywall modal */}
      {showPayModal && (
        <div className={styles.payModal}>
          <div className={styles.payModalContent}>
            <h3>Скоро: платный пакет документов</h3>
            <p>Тестируем цену 150–390 ₽.</p>
            <div className={styles.modalActions}>
              <button
                className={styles.closeBtn}
                onClick={() => setShowPayModal(false)}
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
