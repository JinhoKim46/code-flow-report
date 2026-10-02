from anthropic import Anthropic
from pydantic import BaseModel

MODEL = "demo-model-1"
client = Anthropic()


class Answer(BaseModel):
    text: str


def answer(question):
    msg = client.messages.create(
        model=MODEL,
        max_tokens=512,
        temperature=0.2,
        system="You answer briefly.",
        messages=[{"role": "user", "content": question}],
        output_format=Answer,
    )
    return msg.content
