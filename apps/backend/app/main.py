from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .calendar_store import init_db, seed
from .routers import health, branches, hours, chat, calendar, sessions, enroll

app = FastAPI(title="Olivia API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _startup():
    init_db()
    seed(seed=42, days=21)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(branches.router, prefix="/api/v1", tags=["branches"])
app.include_router(hours.router, prefix="/api/v1", tags=["hours"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(calendar.router, prefix="/api/v1", tags=["calendar"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(enroll.router, prefix="/api/v1", tags=["enroll"])
