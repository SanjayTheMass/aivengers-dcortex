const API_URL = "http://localhost:8000";


export async function getSessions() {
    const response = await fetch(`${API_URL}/sessions`);
    return response.json();
}


export async function createSession() {
    const response = await fetch(`${API_URL}/sessions`, {
        method: "POST"
    });

    return response.json();
}


export async function getMessages(sessionId) {
    const response = await fetch(
        `${API_URL}/sessions/${sessionId}/messages`
    );

    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Unable to load message history");

    return payload.map(({ role, content, tool_trace, ...message }) => ({
        ...message,
        role,
        content,
        trace: tool_trace || []
    }));
}


export async function deleteSession(sessionId) {
    await fetch(
        `${API_URL}/sessions/${sessionId}`,
        {
            method: "DELETE"
        }
    );
}


export async function sendMessage(sessionId, message) {
    const response = await fetch(`${API_URL}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            message
        })
    });

    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Unable to send message");

    return {
        answer: payload.answer,
        spoken: payload.spoken_summary,
        trace: payload.tool_trace
    };
}
