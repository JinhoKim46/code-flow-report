from fastapi import APIRouter

from svc.agent import answer

router = APIRouter(prefix="/v1")


@router.post("/ask")
def ask(question: str):
    """Answers one question."""
    return {"answer": answer(question)}
