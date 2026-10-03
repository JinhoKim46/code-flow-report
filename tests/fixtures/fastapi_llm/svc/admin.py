from fastapi import APIRouter

router = APIRouter(prefix="/admin")


@router.get("/stats")
def stats():
    return {}
