from fastapi import FastAPI
from pydantic import BaseModel
import uuid

app = FastAPI()
SESSIONS = {}

class SessionCreate(BaseModel):
    profession_query: str


class ChatMessage(BaseModel):
    session_id: str
    type: str
    text: str | None = None


def ensure_session(sid: str, profession_query: str | None = None):
    if sid not in SESSIONS:
        SESSIONS[sid] = {
            "profession_query": profession_query or "",
            "state": "awaiting_flow",
            "vacancy_text": None,
            "tasks": None,
            "clarifications": [],
        }
    return SESSIONS[sid]


@app.post("/chat/message")
def chat_message(body: ChatMessage):
    sid = body.session_id
    msg_type = body.type
    text = (body.text or "").strip()

    # Ensure session exists
    session = ensure_session(sid)

    # default response
    reply = ""
    quick_replies = []
    should_show_free_result = False

    state = session.get("state")

    if msg_type == "start":
        session["state"] = "awaiting_flow"
        reply = "Привет 🙂 Супер, что ты решил подойти к найму спокойно. Есть текст вакансии или только описание задач?"
        quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        should_show_free_result = False
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # user messages
    if state == "awaiting_flow":
        low = text.lower()
        if "есть" in low and "ваканс" in low:
            session["state"] = "awaiting_vacancy_text"
            reply = "Понял — вставь, пожалуйста, текст вакансии целиком."
        elif "нет" in low and ("ваканс" in low or "опис" in low):
            session["state"] = "awaiting_tasks"
            reply = "Хорошо — опиши, пожалуйста, 5–10 задач тезисно."
        else:
            reply = "Не совсем понял. Есть текст вакансии или только задачи?"
            quick_replies = ["Есть текст вакансии", "Нет вакансии, есть задачи"]
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_vacancy_text":
        # accept long text
        if len(text) > 200:
            session["vacancy_text"] = text
            session["state"] = "awaiting_clarifications"
            reply = "Спасибо — пара уточнений: 1) город и формат, 2) бюджет, 3) занятость. Ответь одним сообщением."
        else:
            reply = "Пожалуйста, вставь текст вакансии целиком (подробнее, >200 символов)."
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_tasks":
        session["tasks"] = text
        session["state"] = "awaiting_clarifications"
        reply = "Спасибо — пару уточнений: 1) город и формат, 2) бюджет, 3) занятость. Ответь одним сообщением."
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

    if state == "awaiting_clarifications":
        session.setdefault("clarifications", []).append(text)
        session["state"] = "free_ready"
        reply = "Готово! Я собрал бесплатный результат ниже 🙂"
        should_show_free_result = True
        return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": should_show_free_result}

    # fallback
    reply = "Хорошо, записал."
    return {"reply": reply, "quick_replies": quick_replies, "should_show_free_result": False}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/sessions")
def create_session(body: SessionCreate):
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {"profession_query": body.profession_query}
    return {"session_id": session_id}
