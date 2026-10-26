"""TEMPORARY stand-in for the real AI module (ai_agent.py).

It returns a fixed proposal so the frontend and backend can be built and tested
before the Nemotron module is ready. It does NOT call any AI model.
main.py only uses it when ai_agent.py is missing or USE_STUB_AI=true.
/health shows which one is active ("ai": "nemotron" or "stub").
The submitted demo must use the real module.
"""


async def interpret_medication_message(
    user_message: str,
    current_date: str,
    medications: list,
    conversation_context: list,
) -> dict:
    return {
        "action": "add_medication",
        "parameters": {
            "medication_name": "ExampleMed",
            "quantity_collected": 60,
            "collection_date": current_date,
            "daily_quantity": 1,
            "medication_id": None,
        },
        "missing_fields": [],
        "requires_confirmation": True,
        "message": "[STUB AI] Please confirm these medication details before I save them.",
    }
