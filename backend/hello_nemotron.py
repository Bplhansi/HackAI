import os
import sys
import time

import openai
from dotenv import load_dotenv

load_dotenv()  # reads backend/.env into environment variables

api_key = os.getenv("NEBIUS_API_KEY")
base_url = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
model = os.getenv("NEBIUS_MODEL", "nvidia/nemotron-3-super-120b-a12b")

if not api_key or api_key == "your-key-here":
    sys.exit("No API key found. Put your Token Factory key in backend/.env")

client = openai.OpenAI(base_url=base_url, api_key=api_key)


print(f"Asking {model} ...")
start = time.perf_counter()

try:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say hello in one short sentence."}],
        max_tokens=50,
        # Nemotron "thinks" before answering by default. Turning it off makes replies faster.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

except openai.AuthenticationError:
    sys.exit("Your API key was rejected. Check NEBIUS_API_KEY in backend/.env")
except openai.NotFoundError:
    sys.exit(f"Model '{model}' was not found. Check NEBIUS_MODEL in backend/.env")
except openai.APIConnectionError:
    sys.exit("Could not reach Token Factory. Check your internet connection.")

seconds = time.perf_counter() - start
print("Nemotron says:", response.choices[0].message.content)
print(f"Response time: {seconds:.2f} s")