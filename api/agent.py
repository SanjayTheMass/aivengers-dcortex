"""Provider-agnostic tool-use agent.

Works with any OpenAI-compatible chat-completions endpoint:
  OpenAI          AI_BASE_URL=https://api.openai.com/v1          AI_MODEL=gpt-4o
  GitHub Models   AI_BASE_URL=https://models.github.ai/inference AI_MODEL=openai/gpt-4o  (free w/ GitHub PAT)
  Anthropic       AI_BASE_URL=https://api.anthropic.com/v1       AI_MODEL=claude-sonnet-4-5
  Gemini          AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai  AI_MODEL=gemini-2.0-flash
  Groq            AI_BASE_URL=https://api.groq.com/openai/v1     AI_MODEL=llama-3.3-70b-versatile
  Ollama (local)  AI_BASE_URL=http://localhost:11434/v1          AI_MODEL=qwen2.5:14b

Set AI_API_KEY (and optionally AI_BASE_URL / AI_MODEL) in the environment or a .env file.
"""
import json
import os
from pathlib import Path

from openai import OpenAI

from .tools import DISPATCH, openai_tool_specs

# lightweight .env loader (no extra dependency)
_env = Path(__file__).resolve().parents[1] / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE_URL = os.environ.get("AI_BASE_URL", "https://models.github.ai/inference")
MODEL = os.environ.get("AI_MODEL", "openai/gpt-4o")
API_KEY = os.environ.get("AI_API_KEY", os.environ.get("GITHUB_TOKEN", ""))

SYSTEM_PROMPT = """You are the Agentic Crew Ops Advisor for airline Crew Control.
Today's operational dataset covers 2026-09-14 to 2026-09-20 (all times UTC).
The duty-clock snapshot is as of 2026-09-14T18:00Z.

HARD RULES:
1. NEVER compute duty hours, flight hours, FDP, rest gaps or legality yourself.
   ALWAYS call tools — they contain the exact arithmetic for RULE-FDP-01..RULE-BASE-07.
2. Ground every answer in tool output. Cite crew IDs, flight IDs, pairing IDs,
   rule IDs and exact numbers returned by the tools.
3. If a request is ambiguous (missing date, station or crew ID), ask one short
   clarifying question instead of guessing.
4. For disruption questions, chain tools: e.g. sick call -> simulate_sick_call
   for impact; for "what should I do" / cover / recovery questions ALWAYS call
   recommend_cover (it generates ranked, costed, rule-checked options and the
   excluded candidates with reasons) and present its options table faithfully.
5. Show your reasoning briefly: which rules were checked and why an option
   passes or fails. Include rule IDs.
6. ACTIONS: you can change the roster ONLY via the propose_* tools
   (propose_record_sick_call, propose_apply_cover, propose_cancel_pairing_flights).
   These create a PENDING action that the user must approve with the Yes button.
   NEVER claim a change was applied — after proposing, tell the user exactly what
   will change and ask them to approve or reject it. Use get_change_log when
   asked what has changed so far.
7. BE PROACTIVE. When a controller REPORTS an event (not a hypothetical), drive
   the full workflow in ONE turn without waiting to be asked:
   - Sick call reported ("X called in sick", "captain is sick"): in the same turn
     (a) call simulate_sick_call for the impact, (b) call propose_record_sick_call
     so the roster can be updated (user approves via Yes button), (c) call
     recommend_cover and present the ranked options as a numbered list, then
     (d) ask the user to pick an option number. When they pick one, immediately
     call propose_apply_cover (or propose_cancel_pairing_flights for the
     cancellation option) with that option's crew/pairing and ask for approval.
   - Only skip proposing when the user is clearly asking a what-if
     ("what if", "would", "suppose") — then simulate only.
8. End with a one-sentence `spoken_summary` (prefix line "SPOKEN:") that a
   controller could hear over the phone.

Be concise, operational, and precise. A crew controller on a bad day is reading this."""


def _client():
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)


def run_turn(messages, max_steps=12):
    """One user turn with an agentic tool loop.
    `messages` = prior conversation (no system prompt). Returns
    (assistant_text, trace) where trace lists every tool call made."""
    client = _client()
    convo = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    trace = []
    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=MODEL, messages=convo, tools=openai_tool_specs(),
            tool_choice="auto", temperature=0)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or "", trace
        convo.append({"role": "assistant", "content": msg.content,
                      "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = DISPATCH[name](**args)
            except Exception as e:  # surface errors to the model, don't crash
                result = {"error": str(e)}
            trace.append({"tool": name, "args": args, "result": result})
            convo.append({"role": "tool", "tool_call_id": tc.id,
                          "content": json.dumps(result, default=str)[:12000]})
    return "I hit the tool-call limit before finishing — please narrow the question.", trace


def split_spoken(text):
    """Separate the SPOKEN: one-liner from the detailed answer."""
    spoken = None
    lines = []
    for line in (text or "").splitlines():
        if line.strip().upper().startswith("SPOKEN:"):
            spoken = line.split(":", 1)[1].strip()
        else:
            lines.append(line)
    return "\n".join(lines).strip(), spoken
