"""FastAPI service — the scalable entry point (stateless; run N replicas).

Run:  uvicorn api.main:app --reload
POST /chat   {"messages":[{"role":"user","content":"..."}]}
GET  /health
"""
from fastapi import FastAPI
from pydantic import BaseModel

from .agent import run_turn, split_spoken

app = FastAPI(title="Agentic Crew Ops Advisor")


class ChatRequest(BaseModel):
    messages: list  # [{"role": "user"|"assistant", "content": str}, ...]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    text, trace = run_turn(req.messages)
    answer, spoken = split_spoken(text)
    return {"answer": answer, "spoken_summary": spoken, "tool_trace": trace}
