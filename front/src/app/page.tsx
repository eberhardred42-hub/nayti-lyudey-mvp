"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./page.module.css";
import { clearUserSession, getUserToken } from "@/lib/userSession";
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

  const boxRef = useRef<HTMLDivElement | null>(null);

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

  // Автоскролл вниз при новых сообщениях
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, stage, freeReport]);

  async function start() {
    if (!profession.trim()) return;
    const r = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profession_query: profession.trim() }),
    });

    const data = await r.json();
    setSessionId(data.session_id);

    // immediately call backend chat start
    const resp = await fetch("/api/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: data.session_id, type: "start" }),
    });
    const body = await resp.json();
    if (body.reply) setMessages([{ role: "assistant", text: body.reply }]);
    setQuickReplies(body.quick_replies || []);
    if (body.should_show_free_result) setStage("free_result");
    else if ((body.quick_replies || []).length) setStage("choose_flow");
  }

  function pushAssistantOnce(text: string) {
    setMessages((m) => [...m, { role: "assistant", text }]);
  }

  async function fetchFreeReport(sid: string) {
    if (!sid) return;
    setReportLoading(true);
    setReportError(null);
    try {
      const r = await fetch(`/api/report/free?session_id=${sid}`);
      const data = await r.json();
      if (r.ok && data.free_report) {
        setFreeReport(data.free_report);
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
    const r = await fetch("/api/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, type: "user", text }),
    });
    const data = await r.json();
    if (data.reply) setMessages((m) => [...m, { role: "assistant", text: data.reply }]);
    setQuickReplies(data.quick_replies || []);
    if (data.should_show_free_result) {
      setStage("free_result");
      // Fetch the free report
      await fetchFreeReport(sessionId);
    }
    // try to infer stage from reply text
    const low = (data.reply || "").toLowerCase();
    if (low.includes("вставь") && low.includes("ваканс")) setStage("vacancy_text");
    else if (low.includes("опиши") || low.includes("задач")) setStage("tasks");
    else if (low.includes("уточн")) setStage("clarifications");
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
