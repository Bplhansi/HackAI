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

## Team

- Yoshita: frontend
- Hansika: AI
- Aryaa: backend

Frontend

The frontend was built using React, JavaScript, CSS and Vite.

I focused on making CareNest easy to use, especially for older people who might not be very confident with technology.

Features

A dashboard showing medications and their estimated remaining supply.

Reminders when medication is running low.

A calendar to help users see important medication dates.

A medication archive so users can look back at medications they previously tracked.

An emergency information section for allergies and emergency contacts.

Different colour themes and larger text options to make the website more accessible.

A chat interface where users can describe their medication in everyday language.

The frontend currently uses localStorage to save information in the browser and mock responses for the AI chat while the backend integration is being developed.

Setup (frontend)

Open a terminal in the project folder and run:

cd frontend
npm install
npm run dev

Then open the local address shown in the terminal, usually http://localhost:5173/.

To create a version ready for deployment:

npm run build

This creates a dist folder that can be uploaded to Netlify.


## License

MIT - see [LICENSE](LICENSE).
