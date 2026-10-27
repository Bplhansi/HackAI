"""Test setup. Runs before the tests.

Makes sure tests NEVER touch the real Supabase project or the real AI,
even if you have a real .env file.
"""
import os

# Empty values stop load_dotenv() from filling these in from .env
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["USE_STUB_AI"] = "true"
os.environ["DEMO_MODE"] = "true"