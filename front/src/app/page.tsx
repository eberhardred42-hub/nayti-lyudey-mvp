"use client";

import { useState } from "react";

type Msg = { role: "user" | "assistant"; text: string };

export default function Page() {
  const [profession, setProfession] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");

  async function start() {
    if (!profession.trim()) return;

    const r = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profession_query: profession.trim() }),
    });

    const data = await r.json();
    setSessionId(data.session_id);

    setMessages([
      {
        role: "assistant",
        text:
          "Привет 🙂 Супер, что ты решил подойти к найму спокойно и по-человечески.\n" +
          "Ты уже знаешь название роли — или пока есть только задачи?",
      },
    ]);
  }

  function sendLocal() {
    if (!input.trim()) return;
    const userText = input.trim();

    setMessages((m) => [...m, { role: "user", text: userText }]);
    setInput("");

    // Заглушка: пока просто отвечаем, чтобы проверить UX
    setTimeout(() => {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text:
            "Класс, понял 🙂 Давай сделаем это просто: напиши 5–10 задач, которые хочешь делегировать. " +
            "Можно тезисами, как получается.",
        },
      ]);
    }, 250);
  }

  return (
    <main style={{ maxWidth: 720, margin: "40px auto", padding: 16 }}>
      {!sessionId ? (
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
            Запрос: <b>{profession}</b> • Сессия: {sessionId.slice(0, 8)}…
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
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Напиши ответ…"
              style={{
                flex: 1,
                padding: 12,
                border: "1px solid #ddd",
                borderRadius: 10,
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendLocal();
              }}
            />
            <button
              onClick={sendLocal}
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
        </div>
      )}
    </main>
  );
}
