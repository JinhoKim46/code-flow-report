from ai.client import LLMClient
from ai.deps import Deps


def build_deps() -> Deps:
    def make_llm(user_id: int) -> LLMClient:
        return LLMClient()

    return Deps(make_llm=make_llm)
