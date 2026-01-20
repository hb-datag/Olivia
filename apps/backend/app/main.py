from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import health, branches, hours

app = FastAPI(title="Olivia API", version="0.1.0")

# Allow the Vite dev server to call this API in the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(branches.router, prefix="/api/v1", tags=["branches"])
app.include_router(hours.router, prefix="/api/v1", tags=["hours"])
