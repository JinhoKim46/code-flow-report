from openai import OpenAI


class LLMClient:
    def __init__(self, sdk: OpenAI | None = None):
        self.sdk = sdk or OpenAI()

    def chat(self, role: str, messages: list, model: str | None = None) -> str:
        return self.sdk.chat.completions.create(model=model, messages=messages)

    def chat_json(self, role: str, messages: list, schema, model: str | None = None):
        return schema.model_validate_json(self.chat(role, messages, model=model))
