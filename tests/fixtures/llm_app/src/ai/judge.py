from pydantic import BaseModel

from ai.deps import Deps


class Verdict(BaseModel):
    score: int


def judge_messages(text: str) -> list:
    return [{"role": "user", "content": text}]


def run_judge(deps: Deps, text: str) -> Verdict:
    llm = deps.make_llm(1)
    return llm.chat_json("judge", judge_messages(text), Verdict, model="demo-judge", temperature=0)
