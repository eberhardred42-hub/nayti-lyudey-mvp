from fastapi import FastAPI
from pydantic import BaseModel
import uuid

app = FastAPI()
SESSIONS = {}

class SessionCreate(BaseModel):
    profession_query: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/sessions")
def create_session(body: SessionCreate):
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {"profession_query": body.profession_query}
    return {"session_id": session_id}
