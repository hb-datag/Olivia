from fastapi import FastAPI
from .routers import health, branches, hours

app = FastAPI(title="Olivia API", version="0.1.0")

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(branches.router, prefix="/api/v1", tags=["branches"])
app.include_router(hours.router, prefix="/api/v1", tags=["hours"])
