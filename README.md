# medAssist AI

medAssist AI helps people keep track of their medication supply. Tell it in plain
English what you collected ("I picked up 60 tablets of ExampleMed today, one a day")
and it works out when you will run out and reminds you 14 and 7 days before.

> **Disclaimer:** medAssist AI is not medical advice. It only tracks supply.
> Always follow your pharmacist or GP. In an emergency call 999, or NHS 111 for help.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 (Best Apps and Agents).

## How it uses NVIDIA Nemotron

- **Model:** `nvidia/nemotron-3-super-120b-a12b`, called at runtime from
  [`backend/ai_agent.py`](backend/ai_agent.py) on every chat message.
- **Where:** Nebius Token Factory's OpenAI-compatible API at
  `https://api.tokenfactory.nebius.com/v1/`.
- **What Nemotron does:** it reads a message like *"picked up another 28 last Monday"*
  and turns it into a structured proposal (add or update which medication, how many
  tablets, which date, how many a day), or asks a follow-up question when something is
  missing or unclear.
- **What Nemotron does NOT do:** maths or saving. Python works out run-out and reminder
  dates, and nothing is saved until the user checks the pre-filled form and presses Save.

### How the AI is kept safe and reliable
1. **Safety guard first:** questions about changing, skipping or doubling a dose are
   answered with "speak to your pharmacist or GP" and never reach the model.
2. **Strict JSON:** Token Factory's `response_format` with a JSON schema forces the
   reply into our format; Pydantic checks it again. A bad reply gets one retry.
3. **Value checks in code:** impossible quantities, future dates and medication ids the
   model invented are thrown away and turned into a follow-up question.
4. **Date lookup table:** the prompt lists the last 8 days with weekday names, so
   "last Monday" is looked up instead of calculated (this fixed most date mistakes).
5. **Privacy:** logs contain only the action, model and latency, never medication details.

### Where Token Factory accelerated our workflow
- **One API, many models:** because it is OpenAI-compatible, we compared Super,
  Lightning and Nano by changing one line (`NEBIUS_MODEL`), with no new SDK or code.
- **Measured, then chose:** Super was right on every date test; the smaller models were
  faster (see [FEEDBACK.md](FEEDBACK.md)) but made more date mistakes, so we kept Super.
- **Fast enough for chat:** with `enable_thinking: False`, replies take about 1 to 2
  seconds, so we did not need streaming or our own model hosting.
- **Structured output built in:** JSON-schema mode meant we did not need a parsing library.

## Setup (backend)

```
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then put your Token Factory key in .env
python hello_nemotron.py    # checks the connection to Nemotron
python ai_agent.py "I collected 60 tablets of ExampleMed today, one a day"
```

## Frontend

The frontend was built using React, JavaScript, CSS and Vite.

I focused on making medAssist AI easy to use, especially for older people who might not be very confident with technology.

### Features

- A dashboard showing medications and their estimated remaining supply.
- Reminders when medication is running low.
- A calendar to help users see important medication dates.
- A medication archive so users can look back at medications they previously tracked.
- An emergency information section for allergies and emergency contacts.
- Different colour themes and larger text options to make the website more accessible.
- A chat interface where users can describe their medication in everyday language.

The chat sends messages to the backend (`POST /chat`), where Nemotron reads them. When
it understands a collection, the frontend opens the medication form already filled in.
The user checks it and presses Save. Only then is it saved, in the browser
(localStorage, for the dashboard and calendar) and on the backend (`/medications/confirm-add`
or `/confirm-update`), so the assistant can recognise "I collected more" next time.
If the backend can't be reached, the chat falls back to built-in help text.

### Setup (frontend)

Start the backend first (see below), then open a second terminal in the project folder:

```bash
cd frontend
copy .env.example .env   # VITE_API_URL=http://localhost:8000
npm install
npm run dev
```

Then open the local address shown in the terminal, usually `http://localhost:5173/`.

To create a version ready for deployment:

```bash
npm run build
```

This creates a `dist` folder that can be uploaded to Netlify. On Netlify, set the base
directory to `frontend` and add the environment variable `VITE_API_URL` = your Render
backend URL (`frontend/netlify.toml` has the build settings).

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
`test_ai_agent.py` replaces the model with a fake reply to check the safety guard,
the retry on bad JSON, and that invented ids, future dates and silly quantities are rejected.

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
and `USE_STUB_AI=false`). After deploying, open `/health` and check it says
`"ai": "nemotron"`, not `"stub"`.

## Team

- Yoshita: frontend
- Hansika: AI
- Aryaa: backend

## License

MIT - see [LICENSE](LICENSE).