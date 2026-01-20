from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..calendar_store import conn, availability_color

TZ = ZoneInfo("America/New_York")
router = APIRouter()

class EnrollRequest(BaseModel):
    session_id: str
    member_id: str = "demo_member"

@router.post("/enroll")
def enroll(req: EnrollRequest):
    c = conn()
    cur = c.cursor()

    row = cur.execute("""
    SELECT s.capacity, e.enrolled
    FROM sessions s
    JOIN enrollments e ON e.session_id = s.id
    WHERE s.id = ? AND s.status='scheduled'
    """, (req.session_id,)).fetchone()

    if not row:
        c.close()
        raise HTTPException(status_code=404, detail="session not found")

    capacity = int(row["capacity"])
    enrolled = int(row["enrolled"])
    remaining = capacity - enrolled

    # already enrolled?
    existing = cur.execute(
        "SELECT 1 FROM member_enrollments WHERE session_id=? AND member_id=?",
        (req.session_id, req.member_id)
    ).fetchone()
    if existing:
        color = availability_color(enrolled, capacity)
        c.close()
        return {
            "ok": True,
            "already_enrolled": True,
            "session_id": req.session_id,
            "capacity": capacity,
            "enrolled": enrolled,
            "remaining": remaining,
            "availability_color": color
        }

    if remaining <= 0:
        c.close()
        raise HTTPException(status_code=409, detail="class is full")

    now = datetime.now(TZ).isoformat()

    cur.execute(
        "INSERT INTO member_enrollments(session_id, member_id, created_at) VALUES (?,?,?)",
        (req.session_id, req.member_id, now)
    )
    cur.execute(
        "UPDATE enrollments SET enrolled = enrolled + 1, updated_at = ? WHERE session_id = ?",
        (now, req.session_id)
    )
    c.commit()

    updated = cur.execute("""
    SELECT s.capacity, e.enrolled
    FROM sessions s
    JOIN enrollments e ON e.session_id = s.id
    WHERE s.id = ?
    """, (req.session_id,)).fetchone()
    c.close()

    capacity2 = int(updated["capacity"])
    enrolled2 = int(updated["enrolled"])
    remaining2 = capacity2 - enrolled2
    color2 = availability_color(enrolled2, capacity2)

    return {
        "ok": True,
        "already_enrolled": False,
        "session_id": req.session_id,
        "capacity": capacity2,
        "enrolled": enrolled2,
        "remaining": remaining2,
        "availability_color": color2
    }
