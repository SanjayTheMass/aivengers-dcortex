# Setup Guide — Agentic Crew Ops Advisor

Complete instructions to run the system locally, deploy the backend to AWS EC2,
and deploy the React frontend to Vercel.

---

## 1. Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Python | 3.10+ | Backend API + engine |
| Node.js | 18+ | React frontend |
| Any OpenAI-compatible LLM key | — | Agent reasoning (GitHub Models is free) |

---

## 2. Backend — local

```bash
# from the repo root
pip install -r requirements.txt

# build crewops.db from the synthetic dataset (data/*.json)
python etl/load.py

# verify the deterministic engine against the dataset's answer keys
python tests/test_answers.py        # expect 20/20 pass
python tests/test_scenarios.py      # worked disruption scenarios

# configure the AI provider
copy .env.example .env              # then edit .env
```

`.env` keys (any OpenAI-compatible endpoint works):

```
AI_BASE_URL=https://models.inference.ai.azure.com   # GitHub Models (free) — or OpenAI/Anthropic/Gemini/Ollama
AI_MODEL=gpt-4o
AI_API_KEY=<your key>
FRONTEND_URL=http://localhost:5173                  # CORS allow-origin for the React frontend
```

Run the API:

```bash
uvicorn api.main:app --reload       # http://localhost:8000  (docs at /docs)
```

Key endpoints:

| Method / Path | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /sessions` · `GET /sessions` · `PATCH/DELETE /sessions/{sid}` | Multi-chat sessions |
| `GET/DELETE /sessions/{sid}/messages` | History / clear |
| `POST /sessions/{sid}/chat` | Chat turn (server keeps history) |
| `GET /actions` · `POST /actions/{id}/approve` · `POST /actions/{id}/reject` | Human-in-the-loop action gate |
| `GET /changes` | Applied-change audit log |
| `POST /admin/revert` | Restore pristine crewops.db |

---

## 3. Frontend — local (React + Vite)

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173
```

### How the frontend reaches the backend

The frontend calls the **same-origin path `/api/...`**; Vite proxies it to the
backend (see `frontend/vite.config.js`). This avoids browser CORS entirely and
also works around networks that block direct browser requests to a bare EC2 IP.

- **Default**: `/api` → `http://13.217.203.43` (the deployed EC2 backend).
- **To use a local backend instead**, either edit the `target` in
  `vite.config.js` to `http://localhost:8000`, or create `frontend/.env`:

  ```
  VITE_API_URL=http://localhost:8000
  ```

> Note: the Vite proxy strips browser-identifying headers (`User-Agent`,
> `Sec-Fetch-*`) because some corporate networks reject those requests to raw
> IPs with an empty 400.

---

## 4. Streamlit UI (alternative frontend)

The original all-in-one UI still works and talks to the local engine directly:

```bash
streamlit run ui/app.py
```

---

## 5. Backend on AWS EC2

One-time bootstrap on a fresh instance (Amazon Linux or Ubuntu):

```bash
bash deploy/setup-ec2.sh <git-repo-url>
```

This clones the repo, creates a venv, installs dependencies and registers the
`crewops` systemd service (uvicorn). Then:

```bash
sudo systemctl status crewops
curl -s localhost:8000/health        # {"status":"ok"}
```

Checklist for public access:

1. **Security group**: open the serving port (80 recommended; 8000 may be
   filtered by client networks).
2. **CORS**: set `FRONTEND_URL` in the service environment to your deployed
   frontend origin (e.g. `https://<project>.vercel.app`), then
   `sudo systemctl restart crewops`.
3. **Set `.env`** on the instance with your `AI_API_KEY`.

---

## 6. Frontend on Vercel

The project deploys via Git integration (push to `main` auto-deploys).

- `frontend/vercel.json` rewrites `/api/:path*` → `http://13.217.203.43/:path*`,
  so the deployed frontend also calls same-origin `/api` (no CORS needed).
- In the Vercel project settings, set **Root Directory** to `frontend` so the
  rewrite file and build config are picked up.
- If you change the EC2 IP, update it in **both** `frontend/vercel.json`
  (production) and `frontend/vite.config.js` (local dev).

---

## 7. Smoke test

With frontend + backend running:

1. Open the app and click a suggestion, e.g.
   *"Captain C-1042 called in sick for 15 Sep — which flights are uncrewed?"*
2. Expand **View reasoning trace** — every number should come from a tool call.
3. Ask *"Record the sick call"* — a **Pending action** card appears; nothing is
   written until you press **Yes, apply**.
4. Check the sidebar **Database → Change log**, then **Revert to original DB**
   to restore the pristine dataset.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| UI loads but nothing is clickable | Backend unreachable → sessions never load. Check `/api/sessions` in devtools; verify proxy target and that EC2 is up. |
| CORS error in console | `FRONTEND_URL` on the backend doesn't match your origin — or use the `/api` proxy (default) which needs no CORS. |
| Empty `400` from EC2 in the browser only | Network middlebox blocks browser requests to raw IPs. Use the Vite/Vercel `/api` proxy (default setup). |
| `Agent error … AI_API_KEY` | `.env` missing/invalid on the machine running the API. |
| Port 8000 unreachable from your machine | Client network filters it — serve on port 80 (current deployment) or use a domain + HTTPS. |
