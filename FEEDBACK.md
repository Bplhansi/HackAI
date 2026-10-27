# Feedback on Nebius Token Factory

## Getting started

- Time to create an account and get an API key: about 5 minutes
- Anything confusing in the docs:
  - The docs don't say how to switch Nemotron's reasoning on or off. We found
    `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` by trial and error.
  - Model IDs mix capitals and lower case (`nvidia/Nemotron-3_5-Lightning` vs
    `nvidia/nemotron-3-super-120b-a12b`), and they are case-sensitive, so copying
    one wrongly gives a 404. `GET /v1/models` was the reliable way to check.
  - A table of which models support strict `json_schema` output would have saved testing time.

## First call (Phase 1)

| Model                                 | Response time |
| ------------------------------------- | ------------- |
| nvidia/nemotron-3-super-120b-a12b     | 1.45 s        |
| nvidia/Nemotron-3_5-Lightning         | 0.89 s        |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 0.45 s        |

- `enable_thinking: False` worked and made replies fast.

## AI module (ai_agent.py)

### What worked well
- The OpenAI-compatible API meant we used the standard `openai` Python library and
  only changed `base_url`. Swapping models was a one-line change in `.env`.
- Strict `response_format` with a JSON schema worked with Nemotron Super: in our
  testing every reply was valid JSON on the first attempt.
- With reasoning switched off, Super answered chat messages in about 1 to 2.5 seconds.

### What could be better
- The first request after starting was much slower (about 5.6 s) than later ones (about 1 to 2 s).
- Nemotron sometimes worked out weekdays wrongly ("last Monday"). Giving it a
  table of the last 8 dates in the prompt fixed this, but a tip in the docs would help.
- The smaller models were faster but less reliable on dates, so we chose Super.

## Frontend Development Feedback

### My role
I worked on the frontend of medAssist AI using React, JavaScript and CSS. I focused on making the website simple and easy to use, especially for older people who might struggle with technology.

### What worked well
- We could work on different parts of the project at the same time, so I was able to build the website while my teammates worked on the AI and backend.
- I liked how we could use AI to let users enter their medication information in normal sentences instead of having to fill out lots of forms.
- It was useful being able to test the website with mock responses before connecting the actual AI.

### What could be better
- It would be helpful to have more beginner-friendly examples of how to connect Nebius Token Factory to a React website.
- A simple tutorial showing how the frontend, backend and AI all connect together would have made things easier for us.

### What I learned
I learned that building an AI app isn't just about the AI itself. The website also needs to be easy to understand and use. Since medAssist AI is aimed at older people, I tried to focus on clear instructions, larger text and simple buttons.

I also learned how to build and deploy a React website and how to prepare the frontend for connecting to an AI-powered backend.