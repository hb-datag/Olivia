import json
from fastapi import APIRouter, HTTPException
from ..calendar_store import conn, availability_color

router = APIRouter()

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    c = conn()
    row = c.execute("""
    SELECT
      s.id AS session_id,
      s.start_ts, s.end_ts, s.location, s.instructor, s.capacity, s.status,
      b.id AS branch_id, b.name AS branch_name,
      cl.id AS class_id, cl.name AS class_name, cl.bucket, cl.tags_json,
      e.enrolled AS enrolled
    FROM sessions s
    JOIN branches b ON b.id = s.branch_id
    JOIN classes cl ON cl.id = s.class_id
    JOIN enrollments e ON e.session_id = s.id
    WHERE s.id = ?
    """, (session_id,)).fetchone()
    c.close()

    if not row:
        raise HTTPException(status_code=404, detail="session not found")

    cap = int(row["capacity"])
    enrolled = int(row["enrolled"])
    remaining = cap - enrolled
    color = availability_color(enrolled, cap)

    return {
        "session_id": row["session_id"],
        "class_id": row["class_id"],
        "class_name": row["class_name"],
        "bucket": row["bucket"],
        "tags": json.loads(row["tags_json"]),
        "branch_id": row["branch_id"],
        "branch_name": row["branch_name"],
        "start_time": row["start_ts"],
        "end_time": row["end_ts"],
        "location": row["location"],
        "instructor": row["instructor"],
        "capacity": cap,
        "enrolled": enrolled,
        "remaining": remaining,
        "percent_full": (enrolled / cap) if cap else 1.0,
        "availability_color": color
    }
