"""AI-written order summary for the confirmation email."""
from anthropic import Anthropic

from shop.mail import send

MODEL = "demo-model"
client = Anthropic()


def summarise(order, customer_email):
    msg = client.messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0.3,
        system="Write a two-sentence, friendly order confirmation. Never invent items or prices.",
        messages=[{"role": "user", "content": f"Order {order['order_id']}: total {order['total_cents']} cents"}],
    )
    send(customer_email, "Your order", msg.content[0].text)
