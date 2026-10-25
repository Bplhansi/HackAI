# CareNest AI

CareNest AI helps people keep track of their medication supply. Tell it in plain
English what you collected ("I picked up 60 tablets of ExampleMed today, one a day")
and it works out when you will run out and reminds you 14 and 7 days before.

> **Disclaimer:** CareNest AI is not medical advice. It only tracks supply.
> Always follow your pharmacist or GP. In an emergency call 999, or NHS 111 for help.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 (Best Apps and Agents).

## How it uses NVIDIA Nemotron

- Model: `nvidia/nemotron-3-super-120b-a12b`
- Called through **Nebius Token Factory** (OpenAI-compatible API) at
  `https://api.tokenfactory.nebius.com/v1/`
- Reasoning is switched off (`enable_thinking: False`) for faster replies.
- Nemotron only reads the message. Python does all the date and supply maths,
  and nothing is saved until the user confirms.

## Setup (backend)

cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env # then put your Token Factory key in .env
python hello_nemotron.py # checks the connection to Nemotron

## Backend (FastAPI + Supabase)

Routes, request/response shapes and the AI integration contract are in
[backend/API.md](backend/API.md).

### Supabase setup

1. Create a project at supabase.com.
2. SQL Editor -> paste `backend/schema.sql` -> Run.
3. Project Settings -> API: copy the project URL and the **service_role** key into
   `backend/.env` as `SUPABASE_URL` and `SUPABASE_KEY`. The service-role key stays on
   the backend only. It never goes in React or in Git.

### Run the backend

    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload

Open http://localhost:8000/docs to try every route. `GET /health` shows whether the
real AI module (`nemotron`) or the development stub is in use.

Without Supabase variables the backend uses in-memory storage, so you can develop
before the database exists (data is lost on restart).

### Run the tests

    cd backend
    pytest

Tests use an in-memory database and never call Supabase or Nebius.

### Demo user

To keep the hackathon MVP simple, `DEMO_MODE=true` makes everyone share one demo
user and there is no login. Every query is still filtered by user id, and the code
accepts Supabase Auth tokens (`Authorization: Bearer ...`) when `DEMO_MODE=false`.

### Reminder settings

`REPEAT_EVERY_DAYS` (default 3) and `MAX_REPEAT_REMINDERS` (default 5) in `.env`.

### Deploy (Render)

New Web Service from this repo: root directory `backend`, build command
`pip install -r requirements.txt`, start command
`uvicorn main:app --host 0.0.0.0 --port $PORT`. Add every variable from
`.env.example` in Render's Environment tab (set `ALLOWED_ORIGINS` to your frontend URL
and `USE_STUB_AI=false`).

## Team

- Yoshita: frontend
- Hansika: AI
- Aryaa: backend

## License

MIT - see [LICENSE](LICENSE).
