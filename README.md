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

## License

MIT - see [LICENSE](LICENSE).
