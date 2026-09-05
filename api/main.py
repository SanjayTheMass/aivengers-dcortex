"""FastAPI service — stateless chat + persistent sessions / history / multi-tab.

Run:  uvicorn api.main:app --reload

Stateless:  POST /chat  {"messages":[{"role":"user","content":"..."}]}
Sessions:   POST /sessions | GET /sessions | GET|PATCH|DELETE /sessions/{sid}
History:    GET|DELETE /sessions/{sid}/messages
Chat:       POST /sessions/{sid}/chat  {"message":"..."}  (server keeps history)
Multi-tab:  each browser tab creates/loads its own session id.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import sessions as store
from .agent import run_turn, split_spoken

app = FastAPI(title="Agentic Crew Ops Advisor")


class ChatRequest(BaseModel):
    messages: list  # [{"role": "user"|"assistant", "content": str}, ...]


class SessionChatRequest(BaseModel):
    message: str


class SessionCreate(BaseModel):
    title: str = "New chat"


class SessionRename(BaseModel):
    title: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")  # legacy stateless endpoint
def chat(req: ChatRequest):
    text, trace = run_turn(req.messages)
    answer, spoken = split_spoken(text)
    return {"answer": answer, "spoken_summary": spoken, "tool_trace": trace}


# ---- sessions ----
@app.post("/sessions", status_code=201)
def create_session(req: SessionCreate = SessionCreate()):
    return store.create_session(req.title)


@app.get("/sessions")
def list_sessions():
    return store.list_sessions()


@app.get("/sessions/{sid}")
def get_session(sid: str):
    s = store.get_session(sid)
    if not s:
        raise HTTPException(404, "session not found")
    return s


@app.patch("/sessions/{sid}")
def rename_session(sid: str, req: SessionRename):
    if not store.get_session(sid):
        raise HTTPException(404, "session not found")
    return store.rename_session(sid, req.title)


@app.delete("/sessions/{sid}", status_code=204)
def delete_session(sid: str):
    if not store.delete_session(sid):
        raise HTTPException(404, "session not found")


# ---- chat history ----
@app.get("/sessions/{sid}/messages")
def get_history(sid: str, limit: int = 200):
    if not store.get_session(sid):
        raise HTTPException(404, "session not found")
    return store.get_messages(sid, limit)


@app.delete("/sessions/{sid}/messages", status_code=204)
def clear_history(sid: str):
    if not store.get_session(sid):
        raise HTTPException(404, "session not found")
    store.clear_messages(sid)


# ---- session-aware chat (server keeps the history) ----
@app.post("/sessions/{sid}/chat")
def session_chat(sid: str, req: SessionChatRequest):
    s = store.get_session(sid)
    if not s:
        raise HTTPException(404, "session not found")
    msgs = store.history_as_llm_messages(sid) + [{"role": "user", "content": req.message}]
    text, trace = run_turn(msgs)
    answer, spoken = split_spoken(text)
    store.add_message(sid, "user", req.message)
    store.add_message(sid, "assistant", answer, spoken, trace)
    if s["title"] == "New chat":  # auto-title from first message
        store.rename_session(sid, req.message[:60])
    return {"session_id": sid, "answer": answer, "spoken_summary": spoken, "tool_trace": trace}
