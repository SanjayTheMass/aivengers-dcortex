"""Crew Ops Advisor — Streamlit multi-chat UI with voice in (mic) and voice out (TTS).

Run:  streamlit run ui\\app.py
Each chat is a persistent session stored in crewops.db (survives restarts).
Voice input uses the browser's speech recognition (Chrome/Edge).
"""
import json
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import actions as actions_store
from api import sessions as store
from api.agent import run_turn, split_spoken, MODEL, BASE_URL
from engine.actions import ensure_backup

ensure_backup()  # pristine crewops_bkp.db snapshot (created once, never changed)

st.set_page_config(page_title="Crew Ops Advisor", page_icon="X", layout="wide")


def _switch(sid):
    st.session_state.sid = sid


# ---- active session (create/restore) ----
if "sid" not in st.session_state or not store.get_session(st.session_state.sid):
    existing = store.list_sessions()
    st.session_state.sid = existing[0]["id"] if existing else store.create_session()["id"]
sid = st.session_state.sid
session = store.get_session(sid)

st.title("Agentic Crew Ops Advisor")
st.caption(f"Chat: {session['title']} - grounded in crewops.db - all legality math is deterministic - model: {MODEL}")

with st.sidebar:
    st.header("Chats")
    if st.button("+ New chat", use_container_width=True, type="primary"):
        _switch(store.create_session()["id"])
        st.rerun()
    for s in store.list_sessions():
        cols = st.columns([5, 1])
        label = ("> " if s["id"] == sid else "") + s["title"][:40]
        if cols[0].button(label, key=f"open-{s['id']}", use_container_width=True):
            _switch(s["id"])
            st.rerun()
        if cols[1].button("x", key=f"del-{s['id']}", help="Delete chat"):
            store.delete_session(s["id"])
            if s["id"] == sid:
                del st.session_state.sid
            st.rerun()

    with st.expander("Rename / clear"):
        new_title = st.text_input("Title", value=session["title"], key=f"title-{sid}")
        if st.button("Rename") and new_title.strip():
            store.rename_session(sid, new_title.strip())
            st.rerun()
        if st.button("Clear conversation"):
            store.clear_messages(sid)
            st.rerun()

    st.header("Voice")
    voice_out = st.toggle("Speak answers aloud", value=True)

    st.header("Database")
    log = actions_store.change_log()
    if log:
        with st.expander(f"Change log - {len(log)} change(s)"):
            for c in log:
                st.markdown(f"**{c['summary']}**  \n_{c['created_at']}_")
                st.json(c["changes"], expanded=False)
    else:
        st.caption("No changes applied - database is pristine.")
    if log and st.button("Revert to original DB", use_container_width=True):
        st.session_state.confirm_revert = True
    if st.session_state.get("confirm_revert"):
        st.warning("Restore crewops.db from crewops_bkp.db and clear the change log?")
        c1, c2 = st.columns(2)
        if c1.button("Yes, revert", type="primary"):
            r = actions_store.revert()
            st.session_state.confirm_revert = False
            st.toast(r.get("summary", r.get("error", "")))
            st.rerun()
        if c2.button("No, keep changes"):
            st.session_state.confirm_revert = False
            st.rerun()

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

# ---- render history (from the persistent store) ----
history = store.get_messages(sid)
for m in history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant" and m["tool_trace"]:
            with st.expander(f"Reasoning trace - {len(m['tool_trace'])} tool call(s)"):
                for t in m["tool_trace"]:
                    st.markdown(f"**{t['tool']}** `{json.dumps(t['args'])}`")
                    st.json(t["result"], expanded=False)

# ---- pending actions: the human-in-the-loop gate ----
pending = actions_store.list_pending()
if pending:
    st.subheader("Pending actions - your approval required")
    for a in pending:
        with st.container(border=True):
            st.markdown(f"**{a['summary']}**")
            st.caption(f"action: `{a['action']}` - params: `{json.dumps(a['params'])}`")
            c1, c2 = st.columns(2)
            if c1.button("Yes, apply", key=f"yes-{a['id']}", type="primary"):
                r = actions_store.approve(a["id"])
                if r["status"] == "applied":
                    store.add_message(sid, "assistant",
                                      f"APPLIED: {r['summary']}\n\n"
                                      f"Logged {len(r['changes'])} change(s) to the change log.")
                else:
                    store.add_message(sid, "assistant", f"NOT applied: {r['error']}")
                st.rerun()
            if c2.button("No, reject", key=f"no-{a['id']}"):
                actions_store.reject(a["id"])
                store.add_message(sid, "assistant", f"Rejected: {a['summary']} - no changes made.")
                st.rerun()

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
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Checking the data and the rules..."):
            msgs = [{"role": m["role"], "content": m["content"]} for m in history]
            msgs.append({"role": "user", "content": prompt})
            try:
                text, trace = run_turn(msgs)
            except Exception as e:
                text, trace = f"Agent error: {e}\n\nCheck AI_API_KEY / AI_BASE_URL in .env", []
        answer, spoken = split_spoken(text)
        st.markdown(answer)
        if trace:
            with st.expander(f"Reasoning trace - {len(trace)} tool call(s)"):
                for t in trace:
                    st.markdown(f"**{t['tool']}** `{json.dumps(t['args'])}`")
                    st.json(t["result"], expanded=False)
        store.add_message(sid, "user", prompt)
        store.add_message(sid, "assistant", answer, spoken, trace)
        if session["title"] == "New chat":  # auto-title from first message
            store.rename_session(sid, prompt[:60])
        if voice_out and (spoken or answer):
            say = json.dumps(spoken or answer[:300])
            components.html(f"""<script>
                const u = new SpeechSynthesisUtterance({say});
                u.rate = 1.05; speechSynthesis.cancel(); speechSynthesis.speak(u);
            </script>""", height=0)
        if actions_store.list_pending():
            st.rerun()  # surface the approval buttons right away
