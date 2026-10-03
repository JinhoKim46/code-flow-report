import httpx


def decide(payload: dict) -> dict:
    return httpx.post("https://openrouter.ai/api/v1/decisions", json=payload).json()
