from ai.client import LLMClient


class Guard:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def check(self, text: str) -> str:
        return self.llm.chat("guard", [{"role": "user", "content": text}])
