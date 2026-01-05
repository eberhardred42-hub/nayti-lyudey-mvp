"use client";

import { useEffect, useRef, useState } from "react";

type Msg = { role: "user" | "assistant"; text: string };

type Stage =
  | "start"
  | "choose_flow"
  | "vacancy_text"
  | "tasks"
  | "clarifications"
  | "free_result";

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

  const boxRef = useRef<HTMLDivElement | null>(null);

  // автоскролл вниз при новых сообщениях
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, stage]);

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
    if (data.should_show_free_result) setStage("free_result");
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

  // Enter отправляет сообщение
  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleUserSend(input);
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: "40px auto", padding: 16 }}>
      {stage === "start" ? (
        <div>
          <h1 style={{ fontSize: 28, marginBottom: 12 }}>НайтиЛюдей</h1>
          <p style={{ marginBottom: 16, opacity: 0.8 }}>
            Введи профессию или примерно “что нужно сделать”.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={profession}
              onChange={(e) => setProfession(e.target.value)}
              placeholder="Кого ты ищешь?"
              style={{
                flex: 1,
                padding: 12,
                border: "1px solid #ddd",
                borderRadius: 10,
              }}
            />
            <button
              onClick={start}
              style={{
                padding: "12px 16px",
                borderRadius: 10,
                border: "1px solid #ddd",
                cursor: "pointer",
              }}
            >
              Найти
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div style={{ marginBottom: 12, opacity: 0.7 }}>
            Запрос: <b>{profession}</b>
            {sessionId ? (
              <span>
                {' '}3: Сессия: <b>{sessionId.slice(0, 8)}…</b>
              </span>
            ) : null}
          </div>

          <div
            style={{
              border: "1px solid #eee",
              borderRadius: 14,
              padding: 12,
              height: 420,
              overflow: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 10,
              background: "#fff",
            }}
            ref={boxRef}
          >
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "82%",
                  padding: 10,
                  borderRadius: 14,
                  background: m.role === "user" ? "#f3f4f6" : "#fafafa",
                  border: "1px solid #eee",
                  whiteSpace: "pre-wrap",
                }}
              >
                {m.text}
              </div>
            ))}

            {/* быстрые кнопки (quick replies) */}
            {quickReplies.length > 0 && (
              <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                {quickReplies.map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setMessages((m) => [...m, { role: "user", text: q }]);
                      sendToChat(q);
                    }}
                    style={{ padding: 8, borderRadius: 8 }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {/* при free_result показываем блок результата */}
            {stage === "free_result" && (
              <div style={{ marginTop: 8, padding: 12, borderRadius: 10, background: "#fcfdfd" }}>
                <h3 style={{ marginTop: 0 }}>Бесплатный результат</h3>
                <div style={{ marginBottom: 8 }}>
                  <b>Где искать</b>
                  <ul>
                    <li>Платформы для фриланса (Upwork, Freelance.ru)</li>
                    <li>Профессиональные сообщества в Telegram и Slack</li>
                  </ul>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <b>На что смотреть</b>
                  <ul>
                    <li>Портфолио и отзывы</li>
                    <li>Сроки и ответственность</li>
                    <li>Примеры похожих задач</li>
                  </ul>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <b>Сколько стоит</b>
                  <div>Диапазон (заглушка): 15 000–80 000 ₽; стратегия: начать с тестового задания.</div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => setShowPayModal(true)} style={{ padding: 8, borderRadius: 8 }}>
                    Получить полный пакет
                  </button>
                </div>
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                stage === "vacancy_text"
                  ? "Вставь текст вакансии…"
                  : stage === "tasks"
                  ? "Опиши задачи…"
                  : stage === "clarifications"
                  ? `Ответ: ${CLARIFICATIONS[clarIdx] ?? "..."}`
                  : "Напиши сообщение…"
              }
              style={{
                flex: 1,
                padding: 12,
                border: "1px solid #ddd",
                borderRadius: 10,
              }}
              onKeyDown={onKeyDown}
            />
            <button
              onClick={() => handleUserSend(input)}
              style={{
                padding: "12px 16px",
                borderRadius: 10,
                border: "1px solid #ddd",
                cursor: "pointer",
              }}
            >
              Отправить
            </button>
          </div>

          {/* Paywall modal */}
          {showPayModal && (
            <div
              style={{
                position: "fixed",
                left: 0,
                top: 0,
                right: 0,
                bottom: 0,
                background: "rgba(0,0,0,0.4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 60,
              }}
            >
              <div style={{ width: 360, background: "white", padding: 20, borderRadius: 12 }}>
                <h3>Скоро: платный пакет документов</h3>
                <p>Тестируем цену 150–390 ₽.</p>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                  <button onClick={() => setShowPayModal(false)} style={{ padding: 8, borderRadius: 8 }}>
                    Закрыть
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
