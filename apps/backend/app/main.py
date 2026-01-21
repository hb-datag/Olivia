from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import health, branches, hours, calendar, sessions, enroll, chat

app = FastAPI(title="Olivia API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(branches.router, prefix="/api/v1", tags=["branches"])
app.include_router(hours.router, prefix="/api/v1", tags=["hours"])
app.include_router(calendar.router, prefix="/api/v1", tags=["calendar"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(enroll.router, prefix="/api/v1", tags=["enroll"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
