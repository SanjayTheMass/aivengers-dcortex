"""Crew Ops Advisor — Streamlit chat UI with voice in (mic) and voice out (TTS).

Run:  streamlit run ui\\app.py
Voice input uses the browser's speech recognition (Chrome/Edge).
"""
import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.agent import run_turn, split_spoken, MODEL, BASE_URL

st.set_page_config(page_title="Crew Ops Advisor", page_icon="X", layout="wide")
st.title("Agentic Crew Ops Advisor")
st.caption(f"Grounded in crewops.db - all legality math is deterministic - model: {MODEL}")

if "messages" not in st.session_state:
    st.session_state.messages = []   # [{role, content}]
if "traces" not in st.session_state:
    st.session_state.traces = {}     # idx -> tool trace

with st.sidebar:
    st.header("Voice")
    voice_out = st.toggle("Speak answers aloud", value=True)
    st.header("Try asking")
    for q in [
        "Who is on reserve at BLR on 2026-09-15?",
        "How many duty hours does C-1042 have left this week?",
        "Captain C-1042 called in sick for 15 Sep - which flights are uncrewed?",
        "If C-2087 covers P-2291, does anyone breach a duty limit?",
        "BLR is closed 08:00-14:00Z on 17 Sep - what's the impact?",
    ]:
        if st.button(q, use_container_width=True):
            st.session_state.pending = q
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.traces = {}
        st.rerun()

# ---- render history ----
for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant" and i in st.session_state.traces:
            with st.expander(f"Reasoning trace - {len(st.session_state.traces[i])} tool call(s)"):
                for t in st.session_state.traces[i]:
                    st.markdown(f"**{t['tool']}** `{json.dumps(t['args'])}`")
                    st.json(t["result"], expanded=False)

# ---- voice input (browser speech recognition) ----
try:
    from streamlit_mic_recorder import speech_to_text
    voice_text = speech_to_text(language="en", start_prompt="Speak",
                                stop_prompt="Stop", just_once=True, key="stt")
except Exception:
    voice_text = None

typed = st.chat_input("Ask about crew, flights, legality, disruptions...")
prompt = typed or voice_text or st.session_state.pop("pending", None)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Checking the data and the rules..."):
            try:
                text, trace = run_turn(st.session_state.messages)
            except Exception as e:
                text, trace = f"Agent error: {e}\n\nCheck AI_API_KEY / AI_BASE_URL in .env", []
        answer, spoken = split_spoken(text)
        st.markdown(answer)
        if trace:
            with st.expander(f"Reasoning trace - {len(trace)} tool call(s)"):
                for t in trace:
                    st.markdown(f"**{t['tool']}** `{json.dumps(t['args'])}`")
                    st.json(t["result"], expanded=False)
        idx = len(st.session_state.messages)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.traces[idx] = trace
        if voice_out and (spoken or answer):
            say = json.dumps(spoken or answer[:300])
            components.html(f"""<script>
                const u = new SpeechSynthesisUtterance({say});
                u.rate = 1.05; speechSynthesis.cancel(); speechSynthesis.speak(u);
            </script>""", height=0)
