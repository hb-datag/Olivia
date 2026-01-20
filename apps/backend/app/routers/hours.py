import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Query

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[4]   # ~/Olivia
CONFIG_DIR = ROOT_DIR / "configs"
HOURS_PATH = CONFIG_DIR / "hours.json"

TZ = ZoneInfo("America/New_York")

@router.get("/hours")
def get_hours(branch_id: str = Query(...), date: str = Query(..., description="YYYY-MM-DD")):
    cfg = json.loads(HOURS_PATH.read_text())
    day = datetime.fromisoformat(date).astimezone(TZ).strftime("%a").lower()
    rules = cfg["default_hours"]

    hours = rules.get(day)
    if day == "sun":
        if branch_id == cfg["sunday_override"]["open_branch_id"]:
            hours = cfg["sunday_override"]["hours"]
        else:
            hours = None

    return {
        "branch_id": branch_id,
        "date": date,
        "is_closed": hours is None,
        "open_time": None if hours is None else hours[0],
        "close_time": None if hours is None else hours[1]
    }

@router.get("/hours/open-now")
def open_now(branch_id: str = Query(...)):
    cfg = json.loads(HOURS_PATH.read_text())
    now = datetime.now(TZ)
    day = now.strftime("%a").lower()
    rules = cfg["default_hours"]
    hours = rules.get(day)

    if day == "sun":
        if branch_id == cfg["sunday_override"]["open_branch_id"]:
            hours = cfg["sunday_override"]["hours"]
        else:
            hours = None

    if hours is None:
        return {"branch_id": branch_id, "open_now": False, "reason": "closed_today"}

    open_h, open_m = map(int, hours[0].split(":"))
    close_h, close_m = map(int, hours[1].split(":"))
    o = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    c = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    return {"branch_id": branch_id, "open_now": o <= now < c, "now": now.isoformat()}
