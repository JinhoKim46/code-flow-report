from fastapi import FastAPI

from svc import admin
from svc.routes import router

app = FastAPI()
app.include_router(router, prefix="/api")
app.include_router(admin.router, prefix="/api")
