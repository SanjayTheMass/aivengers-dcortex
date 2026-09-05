// Same-origin "/api" is proxied to the EC2 backend by Vite (see vite.config.js),
// which avoids browser CORS issues. Override with VITE_API_URL if needed.
const API_URL = import.meta.env.VITE_API_URL || "/api";

async function json(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Request failed");
    return payload;
}

export async function getSessions() {
    return json(await fetch(`${API_URL}/sessions`));
}

export async function createSession() {
    return json(await fetch(`${API_URL}/sessions`, { method: "POST" }));
}

export async function renameSession(sessionId, title) {
    return json(await fetch(`${API_URL}/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    }));
}

export async function getMessages(sessionId) {
    const payload = await json(await fetch(`${API_URL}/sessions/${sessionId}/messages`));
    return payload.map(({ role, content, tool_trace, ...message }) => ({
        ...message, role, content, trace: tool_trace || [],
    }));
}

export async function clearMessages(sessionId) {
    await fetch(`${API_URL}/sessions/${sessionId}/messages`, { method: "DELETE" });
}

export async function deleteSession(sessionId) {
    await fetch(`${API_URL}/sessions/${sessionId}`, { method: "DELETE" });
}

export async function sendMessage(sessionId, message) {
    const payload = await json(await fetch(`${API_URL}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
    }));
    return { answer: payload.answer, spoken: payload.spoken_summary, trace: payload.tool_trace };
}

// ---- human-in-the-loop actions ----
export async function getPendingActions() {
    return json(await fetch(`${API_URL}/actions`));
}

export async function approveAction(actionId) {
    return json(await fetch(`${API_URL}/actions/${actionId}/approve`, { method: "POST" }));
}

export async function rejectAction(actionId) {
    return json(await fetch(`${API_URL}/actions/${actionId}/reject`, { method: "POST" }));
}

export async function getChangeLog() {
    return json(await fetch(`${API_URL}/changes`));
}

export async function revertDatabase() {
    return json(await fetch(`${API_URL}/admin/revert`, { method: "POST" }));
}
