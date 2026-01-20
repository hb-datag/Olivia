import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from ..calendar_store import conn, availability_color

TZ = ZoneInfo("America/New_York")
router = APIRouter()

@router.get("/calendar")
def get_calendar(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    branch_ids: str | None = Query(None, description="comma-separated, optional"),
    buckets: str | None = Query(None, description="comma-separated, optional"),
    has_spots: bool = Query(False)
):
    start_dt = datetime.fromisoformat(start).replace(tzinfo=TZ)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=TZ) + timedelta(days=1)

    branch_list = [x.strip() for x in branch_ids.split(",")] if branch_ids else None
    bucket_list = [x.strip() for x in buckets.split(",")] if buckets else None

    c = conn()
    q = """
    SELECT
      s.id AS session_id,
      s.start_ts, s.end_ts, s.location, s.instructor, s.capacity,
      b.id AS branch_id, b.name AS branch_name,
      cl.id AS class_id, cl.name AS class_name, cl.bucket, cl.tags_json,
      e.enrolled AS enrolled
    FROM sessions s
    JOIN branches b ON b.id = s.branch_id
    JOIN classes cl ON cl.id = s.class_id
    JOIN enrollments e ON e.session_id = s.id
    WHERE s.status='scheduled'
      AND s.start_ts >= ?
      AND s.start_ts < ?
    """
    params = [start_dt.isoformat(), end_dt.isoformat()]

    if branch_list:
        ph = ",".join(["?"] * len(branch_list))
        q += f" AND b.id IN ({ph})"
        params.extend(branch_list)

    if bucket_list:
        ph = ",".join(["?"] * len(bucket_list))
        q += f" AND cl.bucket IN ({ph})"
        params.extend(bucket_list)

    q += " ORDER BY s.start_ts ASC"

    rows = c.execute(q, params).fetchall()
    c.close()

    events = []
    for r in rows:
        cap = int(r["capacity"])
        enrolled = int(r["enrolled"])
        remaining = cap - enrolled
        if has_spots and remaining <= 0:
            continue

        color = availability_color(enrolled, cap)

        events.append({
            "id": r["session_id"],
            "title": r["class_name"],
            "start": r["start_ts"],
            "end": r["end_ts"],
            "extendedProps": {
                "session_id": r["session_id"],
                "branch_id": r["branch_id"],
                "branch_name": r["branch_name"],
                "class_id": r["class_id"],
                "bucket": r["bucket"],
                "tags": json.loads(r["tags_json"]),
                "location": r["location"],
                "instructor": r["instructor"],
                "capacity": cap,
                "enrolled": enrolled,
                "remaining": remaining,
                "percent_full": (enrolled / cap) if cap else 1.0,
                "availability_color": color
            }
        })

    return {"events": events}
