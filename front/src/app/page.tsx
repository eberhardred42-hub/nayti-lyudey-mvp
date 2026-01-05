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
    setStage("choose_flow");
    setMessages([
      {
        role: "assistant",
        text:
          "Привет 🙂 Отлично — получил запрос. У тебя есть готовый текст вакансии, или только список задач?",
      },
    ]);
  }

  function pushAssistantOnce(text: string) {
    setMessages((m) => [...m, { role: "assistant", text }]);
  }

  function handleChoose(hasVacancy: boolean) {
    if (hasVacancy) {
      setStage("vacancy_text");
      pushAssistantOnce("Отлично. Вставь текст вакансии сюда, я посмотрю и дам бесплатный краткий результат.");
    } else {
      setStage("tasks");
      pushAssistantOnce("Хорошо. Опиши, пожалуйста, задачи — тезисно, 3–10 пунктов.");
    }
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

    // реакция ассистента в зависимости от стадии
    if (stage === "vacancy_text") {
      setTimeout(() => {
        pushAssistantOnce("Понял, спасибо. Нужны пара уточнений, чтобы дать полезный бесплатный результат.");
        startClarifications();
      }, 300);
      return;
    }

    if (stage === "tasks") {
      setTimeout(() => {
        pushAssistantOnce("Отлично, получил задачи. Несколько уточнений — это поможет собрать бесплатный результат.");
        startClarifications();
      }, 300);
      return;
    }

    if (stage === "clarifications") {
      // сохраняем ответ на текущее уточнение
      setClarAnswers((a) => {
        const next = [...a, trimmed];
        return next;
      });

      const nextIdx = clarIdx + 1;
      setClarIdx(nextIdx);

      if (nextIdx < CLARIFICATIONS.length) {
        setTimeout(() => {
          pushAssistantOnce(`Спасибо. Следующее: ${CLARIFICATIONS[nextIdx]}`);
        }, 250);
      } else {
        // завершили уточнения — идём к бесплатному результату
        setTimeout(() => {
          pushAssistantOnce("Готово — формирую короткий бесплатный результат для тебя.");
          setStage("free_result");
        }, 400);
      }
      return;
    }

    // если уже в free_result или choose_flow, даём нейтральный отзыв
    setTimeout(() => {
      pushAssistantOnce("Спасибо — записал. Нажми на нужную кнопку, чтобы продолжить.");
    }, 200);
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

            {/* быстрые кнопки для выбора потока */}
            {stage === "choose_flow" && (
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button
                  onClick={() => handleChoose(true)}
                  style={{ padding: 8, borderRadius: 8 }}
                >
                  Есть текст вакансии
                </button>
                <button
                  onClick={() => handleChoose(false)}
                  style={{ padding: 8, borderRadius: 8 }}
                >
                  Нет вакансии, есть задачи
                </button>
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
