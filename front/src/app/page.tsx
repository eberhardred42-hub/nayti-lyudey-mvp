"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./page.module.css";
import { clearUserSession, getOrCreateUserId, getUserToken } from "@/lib/userSession";
import { UserLoginModal } from "@/components/UserLoginModal";

type Msg = { role: "user" | "assistant"; text: string };

type IntroProgress = { asked: number; max: number; remaining: number };

type IntroResponse = {
  ok: boolean;
  type: "intro_question" | "intro_done";
  reply?: string;
  assistant_text?: string;
  question_text?: string;
  quick_replies?: string[];
  progress?: IntroProgress;
  target_field?: string | null;
  propose_value?: string | null;
  ui_mode?: "confirm_correct" | "free_text";
  brief_snapshot?: Record<string, unknown>;
  free_documents?: Array<{ id: string; title: string; markdown: string }>;
  locked_documents?: Array<{ id: string; title: string; description?: string; price_rub: number; locked: boolean }>;
  ready_to_search?: boolean;
};

type View = "start" | "intro" | "done";

function asRecord(v: unknown): Record<string, unknown> | null {
  if (!v || typeof v !== "object") return null;
  return v as Record<string, unknown>;
}

async function readJsonSafe(resp: Response): Promise<unknown | null> {
  const raw = await resp.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function briefLabel(key: string): string {
  const map: Record<string, string> = {
    source_mode: "Источник",
    problem: "Контекст",
    hiring_goal: "Цель найма",
    role_title: "Роль",
    level: "Уровень",
    location: "Локация",
    work_format: "Формат",
    salary_range: "Бюджет",
    urgency: "Срочность",
    tasks_90d: "Задачи 90 дней",
    must_have: "Must-have",
  };
  return map[key] || key;
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function Page() {
  const [view, setView] = useState<View>("start");
  const [profession, setProfession] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [loginOpen, setLoginOpen] = useState(false);
  const [userToken, setUserTokenState] = useState<string | null>(null);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [quickReplies, setQuickReplies] = useState<string[]>([]);
  const [progress, setProgress] = useState<IntroProgress | null>(null);
  const [uiMode, setUiMode] = useState<"confirm_correct" | "free_text">("free_text");
  const [proposeValue, setProposeValue] = useState<string | null>(null);
  const [correctionMode, setCorrectionMode] = useState(false);
  const [correctionText, setCorrectionText] = useState("");
  const [briefSnapshot, setBriefSnapshot] = useState<Record<string, unknown> | null>(null);
  const [freeDocs, setFreeDocs] = useState<Array<{ id: string; title: string; markdown: string }>>([]);
  const [lockedDocs, setLockedDocs] = useState<
    Array<{ id: string; title: string; description?: string; price_rub: number; locked: boolean }>
  >([]);

  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [payModalOpen, setPayModalOpen] = useState(false);

  const boxRef = useRef<HTMLDivElement | null>(null);
  const correctionRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const sync = () => setUserTokenState(getUserToken());
    sync();
    if (typeof window === "undefined") return;
    window.addEventListener("storage", sync);
    window.addEventListener("nly-auth-changed", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("nly-auth-changed", sync);
    };
  }, []);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, view, freeDocs.length, lockedDocs.length]);

  useEffect(() => {
    if (!correctionMode) return;
    correctionRef.current?.focus();
  }, [correctionMode]);

  const canSend = useMemo(() => {
    if (loading) return false;
    if (!sessionId) return false;
    if (view === "done") return false;
    if (correctionMode) return correctionText.trim().length > 0;
    return input.trim().length > 0;
  }, [loading, sessionId, view, correctionMode, correctionText, input]);

  function authHeaders(): Record<string, string> {
    const token = getUserToken();
    if (token) return { Authorization: `Bearer ${token}` };
    const userId = getOrCreateUserId();
    return userId ? { "X-User-Id": userId } : {};
  }

  async function fetchGuestSafe(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
    const resp = await fetch(input, init);
    if (resp.status !== 401 && resp.status !== 403) return resp;

    // API: guest routes never 401 unless invalid Bearer was provided.
    // Tokens are in-memory on API side; after redeploy an old token becomes invalid.
    const token = getUserToken();
    if (!token) return resp;

    clearUserSession();
    setUserTokenState(null);

    const headers0 = (init.headers || {}) as Record<string, string>;
    const rest: Record<string, string> = { ...headers0 };
    delete rest.Authorization;
    return fetch(input, {
      ...init,
      headers: {
        ...rest,
        ...authHeaders(),
      },
    });
  }

  function resetIntroUi() {
    setMessages([]);
    setQuickReplies([]);
    setProgress(null);
    setUiMode("free_text");
    setProposeValue(null);
    setCorrectionMode(false);
    setCorrectionText("");
    setBriefSnapshot(null);
    setFreeDocs([]);
    setLockedDocs([]);
    setErrorText(null);
  }

  function applyIntroResponse(resp: IntroResponse) {
    const assistantText =
      (typeof resp.reply === "string" && resp.reply) ||
      (typeof resp.assistant_text === "string" && resp.assistant_text) ||
      (typeof resp.question_text === "string" && resp.question_text) ||
      "";
    if (assistantText) setMessages((m) => [...m, { role: "assistant", text: assistantText }]);

    setQuickReplies(Array.isArray(resp.quick_replies) ? resp.quick_replies.map(String).filter(Boolean) : []);
    setProgress(resp.progress && typeof resp.progress === "object" ? (resp.progress as IntroProgress) : null);
    setUiMode(resp.ui_mode === "confirm_correct" ? "confirm_correct" : "free_text");
    setProposeValue(typeof resp.propose_value === "string" ? resp.propose_value : null);
    setBriefSnapshot(resp.brief_snapshot && typeof resp.brief_snapshot === "object" ? (resp.brief_snapshot as Record<string, unknown>) : null);

    if (resp.type === "intro_done") {
      setView("done");
      setQuickReplies([]);
      setUiMode("free_text");
      setProposeValue(null);
      setCorrectionMode(false);
      setCorrectionText("");
      setFreeDocs(Array.isArray(resp.free_documents) ? resp.free_documents : []);
      setLockedDocs(Array.isArray(resp.locked_documents) ? resp.locked_documents : []);
    } else {
      setView("intro");
      setFreeDocs([]);
      setLockedDocs([]);
    }
  }

  async function startIntro() {
    if (!profession.trim()) return;
    setLoading(true);
    setErrorText(null);
    resetIntroUi();
    try {
      const r = await fetchGuestSafe("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ profession_query: profession.trim() }),
      });

      const data = await readJsonSafe(r);
      const dataObj = asRecord(data);
      const sid = typeof dataObj?.session_id === "string" ? dataObj.session_id : "";
      if (!r.ok || !sid) throw new Error("no_session_id");
      setSessionId(sid);

      const resp = await fetchGuestSafe("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sid, type: "intro_start" }),
      });

      const body = await readJsonSafe(resp);
      const bodyObj = asRecord(body);
      if (!resp.ok || !bodyObj) {
        const detail = bodyObj && typeof bodyObj.detail === "string" ? bodyObj.detail : "";
        throw new Error(detail || "intro_start_failed");
      }

      applyIntroResponse(bodyObj as unknown as IntroResponse);
    } catch (e) {
      setErrorText(String(e));
      setMessages([{ role: "assistant", text: "Сервис временно недоступен. Попробуй ещё раз." }]);
      setView("start");
      setSessionId(null);
    } finally {
      setLoading(false);
    }
  }

  async function sendIntroMessage(text: string) {
    if (!sessionId) return;
    const trimmed = (text || "").trim();
    if (!trimmed) return;
    setLoading(true);
    setErrorText(null);
    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setInput("");
    setCorrectionMode(false);
    setCorrectionText("");

    try {
      const r = await fetchGuestSafe("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        credentials: "include",
        body: JSON.stringify({ session_id: sessionId, type: "intro_message", text: trimmed }),
      });

      const data = await readJsonSafe(r);
      const dataObj = asRecord(data);
      if (!r.ok || !dataObj) {
        const detail = dataObj && typeof dataObj.detail === "string" ? dataObj.detail : "";
        throw new Error(detail || "intro_message_failed");
      }
      applyIntroResponse(dataObj as unknown as IntroResponse);
    } catch (e) {
      setErrorText(String(e));
      setMessages((m) => [...m, { role: "assistant", text: "Ошибка. Попробуй ещё раз." }]);
    } finally {
      setLoading(false);
    }
  }

  const progressText = useMemo(() => {
    if (!progress) return "";
    const asked = Math.max(0, Number(progress.asked || 0));
    const max = Math.max(1, Number(progress.max || 10));
    const shown = Math.min(max, asked);
    return `Вопрос ${shown}/${max}`;
  }, [progress]);

  const briefRows = useMemo(() => {
    const snap = briefSnapshot;
    if (!snap) return [] as Array<{ k: string; v: string }>;
    const keys = [
      "role_title",
      "level",
      "location",
      "work_format",
      "salary_range",
      "urgency",
      "problem",
      "hiring_goal",
      "tasks_90d",
      "must_have",
    ];
    return keys.map((k) => ({ k, v: renderValue(snap[k]) }));
  }, [briefSnapshot]);

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
        onLoggedIn={() => setUserTokenState(getUserToken())}
      />

      {view === "start" ? (
        <div className={styles.searchMode}>
          <div className={styles.searchBox}>
            <input
              className={styles.searchInput}
              value={profession}
              onChange={(e) => setProfession(e.target.value)}
              placeholder="Кого ищете? Например: Head of Sales"
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter") void startIntro();
              }}
            />
            <button className={styles.searchBtn} disabled={loading || !profession.trim()} onClick={() => void startIntro()}>
              {loading ? "Запускаю…" : "Начать"}
            </button>
          </div>
          {errorText ? <div className={styles.inlineError}>{errorText}</div> : null}
        </div>
      ) : (
        <div className={styles.chatMode}>
          <div className={styles.topQuery}>
            <div className={styles.topQueryRow}>
              <div>
                <div className={styles.topQueryLabel}>Поиск</div>
                <div className={styles.topQueryText}>{profession || "—"}</div>
              </div>
              <div className={styles.topRightMeta}>
                {progressText ? <span className={styles.progressBadge}>{progressText}</span> : null}
                <button
                  className={styles.secondaryBtn}
                  onClick={() => {
                    setView("start");
                    setSessionId(null);
                    resetIntroUi();
                  }}
                >
                  С начала
                </button>
              </div>
            </div>
          </div>

          <div className={styles.messagesArea} ref={boxRef}>
            {messages.map((m, idx) => (
              <div
                key={idx}
                className={`${styles.message} ${m.role === "user" ? styles.messageUser : styles.messageAssistant}`}
              >
                {m.text}
              </div>
            ))}

            {view === "done" ? (
              <div className={styles.doneArea}>
                <h3 className={styles.doneTitle}>Бриф готов</h3>

                {briefRows.length ? (
                  <div className={styles.briefBox}>
                    <div className={styles.briefTitle}>Черновик брифа (P0)</div>
                    <div className={styles.briefGrid}>
                      {briefRows.map((row) => (
                        <div key={row.k} className={styles.briefRow}>
                          <div className={styles.briefKey}>{briefLabel(row.k)}</div>
                          <pre className={styles.briefVal}>{row.v}</pre>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {freeDocs.length ? (
                  <div className={styles.docsSection}>
                    <h4 className={styles.docsTitle}>Бесплатные результаты</h4>
                    <div className={styles.docsList}>
                      {freeDocs.map((d) => (
                        <details key={d.id} className={styles.docCard} open={false}>
                          <summary className={styles.docSummary}>{d.title}</summary>
                          <pre className={styles.docMarkdown}>{d.markdown}</pre>
                        </details>
                      ))}
                    </div>
                  </div>
                ) : null}

                {lockedDocs.length ? (
                  <div className={styles.docsSection}>
                    <h4 className={styles.docsTitle}>Платные документы</h4>
                    <div className={styles.lockedGrid}>
                      {lockedDocs.map((d) => (
                        <div key={d.id} className={styles.lockedCard}>
                          <div className={styles.lockedTitle}>{d.title}</div>
                          {d.description ? <div className={styles.lockedDesc}>{d.description}</div> : null}
                          <div className={styles.lockedFooter}>
                            <div className={styles.lockedPrice}>{d.price_rub} ₽</div>
                            <button className={styles.fullPackageBtn} onClick={() => setPayModalOpen(true)}>
                              Купить
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className={styles.lockedHint}>PDF/пакеты не генерируются до выбора и оплаты.</div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>

          {view !== "done" ? (
            <div className={styles.composerArea}>
              {uiMode === "confirm_correct" && proposeValue ? (
                <div className={styles.confirmBox}>
                  <div className={styles.confirmText}>Подтвердить значение: “{proposeValue}”?</div>
                  {!correctionMode ? (
                    <div className={styles.confirmActions}>
                      <button className={styles.sendBtn} disabled={loading} onClick={() => void sendIntroMessage("Да")}>
                        Подтвердить
                      </button>
                      <button
                        className={styles.secondaryBtn}
                        disabled={loading}
                        onClick={() => {
                          setCorrectionMode(true);
                          setCorrectionText(proposeValue);
                        }}
                      >
                        Исправить
                      </button>
                    </div>
                  ) : (
                    <div className={styles.composerRow}>
                      <input
                        ref={correctionRef}
                        className={styles.composerInput}
                        value={correctionText}
                        onChange={(e) => setCorrectionText(e.target.value)}
                        placeholder="Введи правильное значение"
                        disabled={loading}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void sendIntroMessage(correctionText);
                        }}
                      />
                      <button className={styles.sendBtn} disabled={!canSend} onClick={() => void sendIntroMessage(correctionText)}>
                        Отправить
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className={styles.composerRow}>
                    <input
                      className={styles.composerInput}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder="Ответ…"
                      disabled={loading}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void sendIntroMessage(input);
                      }}
                    />
                    <button className={styles.sendBtn} disabled={!canSend} onClick={() => void sendIntroMessage(input)}>
                      {loading ? "…" : "Отправить"}
                    </button>
                  </div>
                  {quickReplies.length ? (
                    <div className={styles.quickReplies}>
                      {quickReplies.map((qr) => (
                        <button
                          key={qr}
                          className={styles.quickReplyBtn}
                          disabled={loading}
                          onClick={() => void sendIntroMessage(qr)}
                        >
                          {qr}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </>
              )}

              {errorText ? <div className={styles.inlineError}>{errorText}</div> : null}
            </div>
          ) : null}
        </div>
      )}

      {payModalOpen ? (
        <div className={styles.payModal} onClick={() => setPayModalOpen(false)}>
          <div className={styles.payModalContent} onClick={(e) => e.stopPropagation()}>
            <h3>Оплата</h3>
            <p>Оплата пока не подключена в MVP. Но важно: документы не генерируются автоматически до оплаты.</p>
            <div className={styles.modalActions}>
              <button className={styles.closeBtn} onClick={() => setPayModalOpen(false)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
