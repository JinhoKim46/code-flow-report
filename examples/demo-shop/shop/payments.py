"""External payment provider (invented API)."""
import os

import requests

API = os.environ.get("PAYMENTS_URL", "https://payments.example.invalid")


def charge(order_id, total_cents, card_token):
    """One charge per order — the order id doubles as the idempotency key."""
    r = requests.post(f"{API}/charges", json={"amount": total_cents, "currency": "EUR", "source": card_token},
                      headers={"Idempotency-Key": f"order-{order_id}"}, timeout=10)
    r.raise_for_status()
    return r.json()["id"]
