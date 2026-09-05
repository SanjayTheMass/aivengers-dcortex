import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getSessions, createSession, getMessages, deleteSession, sendMessage,
  renameSession, clearMessages, getPendingActions, approveAction, rejectAction,
  getChangeLog, revertDatabase,
} from "./api";
import "./App.css";
import VoiceInput from "./VoiceInput";

const suggestions = [
  "Who is on reserve at BLR on 2026-09-15?",
  "How many duty hours does C-1042 have left this week?",
  "Captain C-1042 called in sick for 15 Sep - which flights are uncrewed?",
  "If C-2087 covers P-2291, does anyone breach a duty limit?",
  "BLR is closed 08:00-14:00Z on 17 Sep - what's the impact?",
];

function Icon({ name, size = 18 }) {
  const paths = {
    plus: <><path d="M12 5v14M5 12h14" /></>,
    send: <path d="m22 2-7 20-4-9-9-4Z" />,
    trash: <><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5M14 11v5" /></>,
    sparkles: <><path d="m12 3-1.6 5.4L5 10l5.4 1.6L12 17l1.6-5.4L19 10l-5.4-1.6L12 3Z" /><path d="m19 16-.8 2.2L16 19l2.2.8L19 22l.8-2.2L22 19l-2.2-.8L19 16Z" /></>,
    chevron: <path d="m9 18 6-6-6-6" />,
    audio: <><path d="M11 5 6 9H3v6h3l5 4V5Z" /><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10" /></>,
    check: <path d="M20 6 9 17l-5-5" />,
    x: <path d="M18 6 6 18M6 6l12 12" />,
    pencil: <><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" /></>,
    rotate: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [voiceOut, setVoiceOut] = useState(true);
  const [pendingActions, setPendingActions] = useState([]);
  const [changeLog, setChangeLog] = useState([]);
  const [confirmRevert, setConfirmRevert] = useState(false);

  // Sessions and ops state are intentionally loaded once when the app mounts.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadSessions(); refreshOps(); }, []);

  async function refreshOps() {
    try {
      const [actions, log] = await Promise.all([getPendingActions(), getChangeLog()]);
      setPendingActions(actions);
      setChangeLog(log);
    } catch { /* backend unreachable; retried on next send */ }
  }

  async function loadSessions() {
    const data = await getSessions();
    setSessions(data);
    if (data.length > 0) openSession(data[0].id, data);
    else { const session = await createSession(); setSessions([session]); setActiveSession(session); setMessages([]); }
  }
  async function openSession(id, collection = sessions) {
    const session = collection.find((item) => item.id === id);
    if (session) setActiveSession(session);
    setMessages(await getMessages(id));
  }
  async function handleNewChat() {
    const session = await createSession();
    setSessions((prev) => [session, ...prev]);
    setActiveSession(session);
    setMessages([]);
  }
  async function handleDelete(id) {
    await deleteSession(id);
    const remaining = sessions.filter((session) => session.id !== id);
    setSessions(remaining);
    if (activeSession?.id === id) { if (remaining.length) openSession(remaining[0].id, remaining); else handleNewChat(); }
  }
  async function handleRename(id, title) {
    const updated = await renameSession(id, title);
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, ...updated } : s)));
    if (activeSession?.id === id) setActiveSession((prev) => ({ ...prev, ...updated }));
  }
  async function handleClear() {
    if (!activeSession) return;
    await clearMessages(activeSession.id);
    setMessages([]);
  }
  async function handleSend(text) {
    const userMessage = (typeof text === "string" ? text : input).trim();
    if (!userMessage || !activeSession || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);
    try {
      const result = await sendMessage(activeSession.id, userMessage);
      setMessages((prev) => [...prev, { role: "assistant", content: result.answer, trace: result.trace }]);
      if (activeSession.title === "New chat") handleRename(activeSession.id, userMessage.slice(0, 60));
      if (voiceOut && result.spoken) speak(result.spoken);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "I couldn't reach the operations agent. Please try again." }]);
    } finally {
      setLoading(false);
      refreshOps(); // surface any newly proposed actions for approval
    }
  }
  async function handleApprove(action) {
    try {
      const result = await approveAction(action.id);
      const note = result.status === "applied"
        ? `APPLIED: ${result.summary}\n\nLogged ${result.changes.length} change(s) to the change log.`
        : `NOT applied: ${result.error}`;
      setMessages((prev) => [...prev, { role: "assistant", content: note }]);
    } catch (error) {
      setMessages((prev) => [...prev, { role: "assistant", content: `NOT applied: ${error.message}` }]);
    }
    refreshOps();
  }
  async function handleReject(action) {
    try { await rejectAction(action.id); } catch { /* already resolved */ }
    setMessages((prev) => [...prev, { role: "assistant", content: `Rejected: ${action.summary} - no changes made.` }]);
    refreshOps();
  }
  async function handleRevert() {
    try {
      const result = await revertDatabase();
      setMessages((prev) => [...prev, { role: "assistant", content: result.summary || "Database reverted." }]);
    } catch (error) {
      setMessages((prev) => [...prev, { role: "assistant", content: `Revert failed: ${error.message}` }]);
    }
    setConfirmRevert(false);
    refreshOps();
  }
  function speak(text) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions} activeSession={activeSession} onNewChat={handleNewChat}
        onOpen={openSession} onDelete={handleDelete} onRename={handleRename} onClear={handleClear}
        voiceOut={voiceOut} setVoiceOut={setVoiceOut}
        changeLog={changeLog} confirmRevert={confirmRevert} setConfirmRevert={setConfirmRevert} onRevert={handleRevert}
      />
      <main className="chat-panel">
        <header className="chat-header">
          <div className="title-block">
            <div className="eyebrow"><span className="status-dot" />Operations assistant</div>
            <h1>{activeSession?.title || "New conversation"}</h1>
          </div>
          <button className="icon-button header-action" type="button" title="Toggle audio responses" onClick={() => setVoiceOut(!voiceOut)}><Icon name="audio" /></button>
        </header>
        <section className="messages" aria-live="polite">
          {messages.length === 0 && !loading && pendingActions.length === 0
            ? <Welcome onSelect={(q) => handleSend(q)} />
            : messages.map((message, index) => <Message key={index} message={message} />)}
          {loading && <div className="message assistant-message"><div className="assistant-avatar"><Icon name="sparkles" size={16} /></div><div className="thinking"><span /><span /><span /></div></div>}
          {pendingActions.length > 0 && (
            <div className="pending-actions">
              <h3>Pending actions — your approval required</h3>
              {pendingActions.map((action) => (
                <div className="pending-card" key={action.id}>
                  <p className="pending-summary">{action.summary}</p>
                  <p className="pending-meta">action: <code>{action.action}</code> · params: <code>{JSON.stringify(action.params)}</code></p>
                  <div className="pending-buttons">
                    <button type="button" className="approve" onClick={() => handleApprove(action)}><Icon name="check" size={15} />Yes, apply</button>
                    <button type="button" className="reject" onClick={() => handleReject(action)}><Icon name="x" size={15} />No, reject</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
        <div className="composer-wrap">
          <div className="composer">
            <input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); handleSend(); } }} placeholder="Ask about crew, flights, legality, disruptions…" aria-label="Message the operations assistant" />
            <VoiceInput onResult={(text) => handleSend(text)} />
            <button className="send-button" type="button" onClick={() => handleSend()} disabled={!input.trim() || loading} aria-label="Send message"><Icon name="send" size={17} /></button>
          </div>
          <p className="composer-note">AI can make mistakes. Verify critical operational decisions.</p>
        </div>
      </main>
    </div>
  );
}

function Sidebar({ sessions, activeSession, onNewChat, onOpen, onDelete, onRename, onClear, voiceOut, setVoiceOut, changeLog, confirmRevert, setConfirmRevert, onRevert }) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="brand"><div className="brand-mark"><Icon name="sparkles" size={17} /></div><span>CrewOps Advisor</span></div>
        <button className="new-chat" type="button" onClick={onNewChat}><Icon name="plus" size={17} />New conversation</button>
      </div>
      <nav className="session-list" aria-label="Conversations">
        <p className="section-label">Recent conversations</p>
        {sessions.map((session) => (
          <div key={session.id} className={`session ${activeSession?.id === session.id ? "active" : ""}`}>
            <button className="session-name" type="button" onClick={() => onOpen(session.id)}><span>{session.title || "Untitled conversation"}</span><Icon name="chevron" size={15} /></button>
            <button className="delete-button" type="button" onClick={() => onDelete(session.id)} aria-label={`Delete ${session.title || "conversation"}`}><Icon name="trash" size={15} /></button>
          </div>
        ))}
      </nav>
      {activeSession && (
        <div className="session-tools">
          {renaming ? (
            <form className="rename-form" onSubmit={(event) => { event.preventDefault(); if (title.trim()) onRename(activeSession.id, title.trim()); setRenaming(false); }}>
              <input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus aria-label="New title" />
              <button type="submit">Save</button>
            </form>
          ) : (
            <button type="button" className="tool-button" onClick={() => { setTitle(activeSession.title || ""); setRenaming(true); }}><Icon name="pencil" size={14} />Rename chat</button>
          )}
          <button type="button" className="tool-button" onClick={onClear}><Icon name="trash" size={14} />Clear conversation</button>
        </div>
      )}
      <div className="db-panel">
        <p className="section-label">Database</p>
        {changeLog.length === 0 ? <p className="db-note">No changes applied — database is pristine.</p> : (
          <>
            <details className="changelog">
              <summary>Change log · {changeLog.length} change{changeLog.length === 1 ? "" : "s"}</summary>
              {changeLog.map((change) => (
                <div className="changelog-item" key={change.id}>
                  <strong>{change.summary}</strong>
                  <em>{change.created_at}</em>
                  <pre>{JSON.stringify(change.changes, null, 2)}</pre>
                </div>
              ))}
            </details>
            {confirmRevert ? (
              <div className="revert-confirm">
                <p>Restore crewops.db from backup and clear the change log?</p>
                <div>
                  <button type="button" className="approve" onClick={onRevert}>Yes, revert</button>
                  <button type="button" className="reject" onClick={() => setConfirmRevert(false)}>No, keep</button>
                </div>
              </div>
            ) : (
              <button type="button" className="tool-button danger" onClick={() => setConfirmRevert(true)}><Icon name="rotate" size={14} />Revert to original DB</button>
            )}
          </>
        )}
      </div>
      <div className="voice-settings">
        <div><p className="settings-title">Voice responses</p><p className="settings-copy">Read answers aloud</p></div>
        <button type="button" role="switch" aria-checked={voiceOut} className={`switch ${voiceOut ? "checked" : ""}`} onClick={() => setVoiceOut(!voiceOut)}><span /></button>
      </div>
    </aside>
  );
}

function Welcome({ onSelect }) {
  return (
    <div className="welcome">
      <div className="welcome-icon"><Icon name="sparkles" size={24} /></div>
      <h2>How can I help with operations?</h2>
      <p>Get quick, grounded answers about crew, flights, legality, and disruptions.</p>
      <div className="suggestions">
        {suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => onSelect(suggestion)}><span>{suggestion}</span><Icon name="chevron" size={16} /></button>)}
      </div>
    </div>
  );
}

function Message({ message }) {
  const isUser = message.role === "user";
  return (
    <article className={`message ${isUser ? "user-message" : "assistant-message"}`}>
      {!isUser && <div className="assistant-avatar"><Icon name="sparkles" size={16} /></div>}
      <div className="message-body">
        <div className="message-label">{isUser ? "You" : "CrewOps Advisor"}</div>
        <div className={`message-content ${isUser ? "" : "markdown"}`}>
          {isUser ? message.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || ""}</ReactMarkdown>}
        </div>
        {message.trace?.length > 0 && (
          <details className="trace">
            <summary>View reasoning trace · {message.trace.length} tool call{message.trace.length === 1 ? "" : "s"}</summary>
            {message.trace.map((tool, index) => (
              <div className="trace-item" key={index}>
                <strong>{tool.tool}</strong> <code>{JSON.stringify(tool.args)}</code>
                <pre>{JSON.stringify(tool.result, null, 2)}</pre>
              </div>
            ))}
          </details>
        )}
      </div>
    </article>
  );
}

export default App;
