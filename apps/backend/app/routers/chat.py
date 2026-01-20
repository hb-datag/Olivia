import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel
from rapidfuzz import process, fuzz

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[4]  # ~/Olivia
CONFIG_DIR = ROOT_DIR / "configs"
FACILITIES_PATH = CONFIG_DIR / "facilities.json"
HOURS_PATH = CONFIG_DIR / "hours.json"

TZ = ZoneInfo("America/New_York")

DOW_INDEX = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

CANONICAL_DOW = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}

class UiContext(BaseModel):
    branch_id: str | None = None
    date: str | None = None  # YYYY-MM-DD

class ChatRequest(BaseModel):
    message: str
    ui_context: UiContext | None = None

def _load_branches():
    data = json.loads(FACILITIES_PATH.read_text())
    branches = data["branches"]
    for b in branches:
        b["aliases"] = b.get("aliases", [])
    return branches

def _resolve_branch_id(message: str, ui_branch_id: str | None):
    branches = _load_branches()

    if ui_branch_id and any(b["id"] == ui_branch_id for b in branches):
        return ui_branch_id

    for b in branches:
        if b["id"] in message:
            return b["id"]

    choices = []
    mapping = {}
    for b in branches:
        choices.append(b["name"])
        mapping[b["name"]] = b["id"]
        for a in b["aliases"]:
            choices.append(a)
            mapping[a] = b["id"]

    match = process.extractOne(message, choices, scorer=fuzz.WRatio)
    if match and match[1] >= 80:
        return mapping[match[0]]

    return None

def _extract_dow(message: str) -> int | None:
    for key, idx in DOW_INDEX.items():
        if re.search(rf"\b{re.escape(key)}\b", message):
            return idx
    return None

def _resolve_date(message: str, ui_date: str | None):
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", message)
    if m:
        return m.group(1)

    now = datetime.now(TZ)

    dow = _extract_dow(message)
    if dow is not None:
        days_ahead = (dow - now.weekday()) % 7
        target = now + timedelta(days=days_ahead)
        return target.strftime("%Y-%m-%d")

    return ui_date or now.strftime("%Y-%m-%d")

def _get_hours(branch_id: str, date_str: str):
    cfg = json.loads(HOURS_PATH.read_text())
    dt = datetime.fromisoformat(date_str).replace(tzinfo=TZ)
    day = dt.strftime("%a").lower()
    rules = cfg["default_hours"]

    hours = rules.get(day)
    if day == "sun":
        if branch_id == cfg["sunday_override"]["open_branch_id"]:
            hours = cfg["sunday_override"]["hours"]
        else:
            hours = None

    return hours  # None or ["HH:MM","HH:MM"]

def _open_now(branch_id: str):
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
        return False, "closed_today"

    open_h, open_m = map(int, hours[0].split(":"))
    close_h, close_m = map(int, hours[1].split(":"))
    o = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    c = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return (o <= now < c), None

@router.post("/chat")
def chat(req: ChatRequest):
    msg = (req.message or "").strip()
    msg_l = msg.lower()

    ui_branch = req.ui_context.branch_id if req.ui_context else None
    ui_date = req.ui_context.date if req.ui_context else None

    branch_id = _resolve_branch_id(msg_l, ui_branch)
    if not branch_id:
        return {
            "assistant_message": "Which YMCA location do you mean?",
            "follow_up_question": "Which branch should I use?",
            "intent": {"intent_name": "get_hours", "missing_slots": ["branch_id"]},
        }

    if "open now" in msg_l or "open right now" in msg_l:
        is_open, reason = _open_now(branch_id)
        if is_open:
            text = "Yes — you’re open right now."
        else:
            text = "No — you’re closed right now." if reason else "No — not open right now."
        return {
            "assistant_message": text,
            "follow_up_question": None,
            "intent": {"intent_name": "open_now", "parameters": {"branch_id": branch_id}},
        }

    date_str = _resolve_date(msg_l, ui_date)
    dow_idx = _extract_dow(msg_l)
    dow_label = CANONICAL_DOW.get(dow_idx) if dow_idx is not None else None

    hours = _get_hours(branch_id, date_str)
    if hours is None:
        text = f"Closed on {date_str}."
    else:
        text = f"Hours on {date_str}: {hours[0]}–{hours[1]}."

    if dow_label:
        text = f"On {dow_label} ({date_str}): " + ("Closed." if hours is None else f"{hours[0]}–{hours[1]}.")

    return {
        "assistant_message": text,
        "follow_up_question": None,
        "intent": {"intent_name": "get_hours", "parameters": {"branch_id": branch_id, "date": date_str}},
    }
