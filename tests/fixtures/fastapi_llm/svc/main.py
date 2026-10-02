from fastapi import FastAPI

from svc.routes import router

app = FastAPI()
app.include_router(router, prefix="/api")
