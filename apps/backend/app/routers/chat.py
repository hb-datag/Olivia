import json
import re
from datetime import datetime, timedelta
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

OLIVIA_GREETING = "This is Olivia with the YMCA! How may I help you?"

BUCKET_ALIASES = {
    "kids_club": "kids",
    "kidsclub": "kids",
    "childcare": "kids",
    "kids": "kids",
    "swim": "swim",
    "sports": "sports",
    "gym": "gym",
}



from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..calendar_store import conn, availability_color
from ..llm import ollama_chat_json

TZ = ZoneInfo("America/New_York")
REPO_ROOT = Path(__file__).resolve().parents[2]  # /app (Docker) or ~/Olivia/apps/backend (local)
CONFIGS = Path(__file__).resolve().parents[2] / "configs" if (Path(__file__).resolve().parents[2] / "configs").exists() else Path(__file__).resolve().parents[4] / "configs"
FACILITIES_PATH = CONFIGS / "facilities.json"

router = APIRouter()

MAX_HISTORY = 12
CHAT_HISTORY: Dict[str, List[Dict[str, str]]] = {}
PENDING_CONTEXT: Dict[str, Dict[str, Any]] = {}
LAST_SUGGESTIONS: Dict[str, List[Dict[str, Any]]] = {}

DEFAULT_FRONT_DESK_BRANCH_ID = "campbell_county"
_MEMBER_HOME_CACHE: dict[str, str] = {}

def _member_home_branch(member_id: str | None) -> str | None:
    if not member_id:
        return None
    if member_id in _MEMBER_HOME_CACHE:
        return _MEMBER_HOME_CACHE[member_id]
    try:
        # REPO_ROOT/CONFIGS is already set near the top of this file
        mp = (CONFIGS / 'member_profiles.json')
        if not mp.exists():
            return None
        import json
        data = json.loads(mp.read_text())
        prof = data.get(member_id) or {}
        hb = prof.get('home_branch_id')
        if hb:
            _MEMBER_HOME_CACHE[member_id] = hb
        return hb
    except Exception:
        return None


# ----------------------------
# Member defaults + bucket aliases
# ----------------------------
FRONT_DESK_DEFAULT_BRANCH = "campbell_county"
_MEMBER_PROFILES_CACHE: Optional[Dict[str, Any]] = None

def _load_member_profiles() -> Dict[str, Any]:
    cfg = CONFIGS / "member_profiles.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text())
    except Exception:
        return {}

def _get_member_home_branch(member_id: Optional[str]) -> Optional[str]:
    global _MEMBER_PROFILES_CACHE
    if not member_id:
        return None
    if _MEMBER_PROFILES_CACHE is None:
        _MEMBER_PROFILES_CACHE = _load_member_profiles()
    prof = (_MEMBER_PROFILES_CACHE.get(member_id) or {})
    return prof.get("home_branch_id")

def _default_branch_ids(req) -> Optional[List[str]]:
    # front desk defaults to Campbell County unless explicitly chosen
    if getattr(req.ui_context, "user_group", None) == "front_desk":
        return [FRONT_DESK_DEFAULT_BRANCH]
    if getattr(req.ui_context, "default_branch_id", None):
        return [req.ui_context.default_branch_id]
    mid = getattr(req.ui_context, "member_id", None)
    hb = _get_member_home_branch(mid)
    if hb:
        return [hb]
    return None

_BUCKET_ALIASES = {
    "kids_club": "kids",
    "kids club": "kids",
    "kids": "kids",
}

def _normalize_bucket_ids(buckets: Optional[List[str]]) -> Optional[List[str]]:
    if not buckets:
        return buckets
    out: List[str] = []
    for b in buckets:
        if not b:
            continue
        k = str(b).strip().lower()
        out.append(_BUCKET_ALIASES.get(k, k))
    return out or None

def _match_branch_id_from_text(branches: List[Dict[str, Any]], message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    msg = message.strip().lower()
    msg_u = msg.replace("-", " ").replace("_", " ")

    # id-ish matches
    for b in branches:
        bid = (b.get("id") or "").lower()
        if not bid:
            continue
        if msg == bid or msg.replace(" ", "_") == bid or msg_u.replace(" ", "_") == bid:
            return b.get("id")

    # name substring matches
    for b in branches:
        name = (b.get("name") or "").lower()
        if name and name in msg:
            return b.get("id")
        if name:
            core = name.replace("ymca", "").strip()
            toks = [t for t in core.split() if t]
            if toks and all(t in msg for t in toks):
                return b.get("id")
    return None


def _now_iso() -> str:
    return datetime.now(TZ).isoformat()

def _week_range_from_now() -> tuple[str, str]:
    now = datetime.now(TZ)
    start = now - timedelta(days=now.weekday())  # Monday
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6)
    return start.date().isoformat(), end.date().isoformat()

def _load_branches() -> List[Dict[str, Any]]:
    cfg = json.loads(FACILITIES_PATH.read_text())
    return cfg["branches"]

def _resolve_branch_id_from_text(branches: list[dict], text: str) -> str | None:
    """
    Match user text like 'Campbell County' or 'Blue Ash YMCA' to a branch_id.
    Deterministic: exact id match, then substring match on branch name.
    """
    if not text:
        return None
    t = text.strip().lower()

    # exact id match
    for b in branches:
        bid = (b.get("id") or "").lower()
        if bid and bid == t:
            return b.get("id")

    # substring match on branch name
    for b in branches:
        name = (b.get("name") or "").lower()
        if name and t in name:
            return b.get("id")

    # loose match: remove 'ymca' and punctuation-ish
    t2 = re.sub(r'[^a-z0-9 ]+', ' ', t).replace("ymca", "").strip()
    for b in branches:
        name = re.sub(r'[^a-z0-9 ]+', ' ', (b.get("name") or "").lower()).replace("ymca", "").strip()
        if t2 and name and t2 in name:
            return b.get("id")

    return None


def _resolve_branch_ids_from_text(branches: List[Dict[str, Any]], text: str) -> Optional[List[str]]:
    t = (text or "").strip().lower()
    if not t:
        return None

    # exact id match
    for b in branches:
        if (b.get("id") or "").lower() == t:
            return [b["id"]]

    # name substring match (handles e.g. "Campbell County")
    t2 = t.replace("ymca", "").strip()
    hits = []
    for b in branches:
        name = (b.get("name") or "").lower()
        if t in name or (t2 and t2 in name):
            hits.append(b)

    if len(hits) == 1:
        return [hits[0]["id"]]
    return None
def _search_sessions(
    date_start: str,
    date_end: str,
    branch_ids: Optional[List[str]],
    buckets: Optional[List[str]],
    tags: Optional[List[str]],
    has_spots: bool,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    c = conn()
    rows = c.execute(
        """
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
          AND date(s.start_ts) >= date(?)
          AND date(s.start_ts) <= date(?)
        """,
        (date_start, date_end),
    ).fetchall()
    c.close()

    out: List[Dict[str, Any]] = []
    tag_set = set([t.lower() for t in (tags or [])])
    bucket_set = set([BUCKET_ALIASES.get(b.lower(), b.lower()) for b in (buckets or [])])

    for r in rows:
        if branch_ids and r["branch_id"] not in branch_ids:
            continue

        r_bucket_raw = (r["bucket"] or "").lower()
        r_bucket = BUCKET_ALIASES.get(r_bucket_raw, r_bucket_raw)
        if bucket_set and r_bucket not in bucket_set:
            continue

        r_tags = [t.lower() for t in json.loads(r["tags_json"])]
        if tag_set and not (tag_set.intersection(r_tags)):
            continue

        cap = int(r["capacity"])
        enrolled = int(r["enrolled"])
        remaining = cap - enrolled
        if has_spots and remaining <= 0:
            continue

        color = availability_color(enrolled, cap)
        out.append(
            {
                "session_id": r["session_id"],
                "class_id": r["class_id"],
                "class_name": r["class_name"],
                "bucket": r["bucket"],
                "tags": json.loads(r["tags_json"]),
                "branch_id": r["branch_id"],
                "branch_name": r["branch_name"],
                "start_time": r["start_ts"],
                "end_time": r["end_ts"],
                "location": r["location"],
                "instructor": r["instructor"],
                "capacity": cap,
                "enrolled": enrolled,
                "remaining": remaining,
                "percent_full": (enrolled / cap) if cap else 1.0,
                "availability_color": color,
            }
        )

    out.sort(key=lambda x: x["start_time"])
    return out[: max(1, min(limit, 10))]



# ----------------------------
# Intelligent suggestion policy (deterministic)
# ----------------------------
def _repo_root_from_here() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "configs").exists():
            return p
    # fallback: go up a few levels
    return here.parents[4]

def _load_branch_proximity() -> Dict[str, List[Dict[str, Any]]]:
    root = _repo_root_from_here()
    cfg = root / "configs" / "branch_proximity.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text())
    except Exception:
        return {}


def _fmt_day(d: str) -> str:
    # d is YYYY-MM-DD
    try:
        dt = date.fromisoformat(d)
        return dt.strftime('%a %b %-d')
    except Exception:
        return d

def _intelligent_suggest_sessions(
    date_start: str,
    date_end: str,
    home_branch_ids: Optional[List[str]],
    buckets: Optional[List[str]],
    tags: Optional[List[str]],
    has_spots: bool,
    limit: int,
    primary_branch_id: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], str]:
    """Return (suggested_sessions, suggestion_note)."""
    home_branch_ids = home_branch_ids or []
    home_id = home_branch_ids[0] if home_branch_ids else None

    # 1) primary: requested day(s) at your Y
    primary = _search_sessions(date_start, date_end, home_branch_ids or None, buckets, tags, has_spots, limit)
    for ss in primary:
        ss['suggestion_tier'] = 'primary'
    if primary:
        bn = primary[0].get('branch_name') or 'your Y'
        note = f"Here are the top options at {bn}:"
        return primary, note

    # widen window for other days (±7d)
    try:
        ds = date.fromisoformat(date_start)
        de = date.fromisoformat(date_end)
    except Exception:
        ds = None
        de = None

    if ds and de:
        win_start = (ds - timedelta(days=7)).isoformat()
        win_end = (de + timedelta(days=7)).isoformat()
    else:
        win_start, win_end = date_start, date_end

    # 2) other day at your Y
    other = _search_sessions(win_start, win_end, home_branch_ids or None, buckets, tags, has_spots, limit)
    # remove anything that matches requested day window
    filtered = []
    for ss in other:
        d0 = (ss.get('start_time') or '')[:10]
        if d0 and (d0 < date_start or d0 > date_end):
            filtered.append(ss)
    other = filtered[:limit]
    for ss in other:
        ss['suggestion_tier'] = 'other_day_at_y'
    if other:
        bn = other[0].get('branch_name') or 'your Y'
        first_day = (other[0].get('start_time') or '')[:10] or ''
        note = f"I’m not seeing anything on {_fmt_day(date_start)} at {bn}, but here are a few options on other days (starting {_fmt_day(first_day)}):"
        return other, note

    # 3) nearby Ys: same day
    prox = _load_branch_proximity() if home_id else {}
    nearby = (prox.get(home_id) or []) if home_id else []
    nearby_ids = [x.get('branch_id') for x in nearby if x.get('branch_id')]
    near_out = []
    for cand in nearby:
        bid = cand.get('branch_id')
        mins = cand.get('drive_minutes')
        if not bid:
            continue
        got = _search_sessions(date_start, date_end, [bid], buckets, tags, has_spots, limit)
        for ss in got:
            ss['suggestion_tier'] = 'nearby_same_day'
            ss['drive_minutes'] = mins
            ss['home_branch_id'] = home_id
        near_out.extend(got)
        if len(near_out) >= limit:
            break
    near_out = sorted(near_out, key=lambda x: x.get('start_time') or '')[:limit]
    if near_out:
        note = f"I’m not seeing matches at your Y on {_fmt_day(date_start)}, but here are a few nearby options the same day:"
        return near_out, note

    # 4) nearby Ys: other days
    near2 = []
    for cand in nearby:
        bid = cand.get('branch_id')
        mins = cand.get('drive_minutes')
        if not bid:
            continue
        got = _search_sessions(win_start, win_end, [bid], buckets, tags, has_spots, limit)
        for ss in got:
            ss['suggestion_tier'] = 'nearby_other_day'
            ss['drive_minutes'] = mins
            ss['home_branch_id'] = home_id
        near2.extend(got)
        if len(near2) >= limit:
            break
    near2 = sorted(near2, key=lambda x: x.get('start_time') or '')[:limit]
    if near2:
        first_day = (near2[0].get('start_time') or '')[:10] or ''
        note = f"I’m not seeing matches at your Y right now, but here are a few nearby options on other days (starting {_fmt_day(first_day)}):"
        return near2, note

    # nothing
    return [], "I couldn't find any matching sessions."

def _branch_name(branches: List[Dict[str, Any]], branch_id: str) -> str:
    for b in branches or []:
        if b.get("id") == branch_id:
            return b.get("name") or b.get("branch_name") or branch_id
    return branch_id

def _is_single_day_range(date_start: str, date_end: str) -> bool:
    try:
        from datetime import date
        ds = date.fromisoformat(date_start)
        de = date.fromisoformat(date_end)
        return (de - ds).days == 1
    except Exception:
        return False

def _search_sessions_with_fallback(
    date_start: str,
    date_end: str,
    branch_ids: Optional[List[str]],
    buckets: Optional[List[str]],
    tags: Optional[List[str]],
    has_spots: bool,
    limit: int,
    branches: List[Dict[str, Any]],
) -> (List[Dict[str, Any]], Dict[str, Any]):
    """
    Deterministic policy:
      1) Primary branch + requested window
      2) If none and single-day: same branch nearby days
      3) If still thin: nearby branches same day (with minutes if known)
    """
    limit = int(limit or 5)
    branch_ids = branch_ids or []
    primary = branch_ids[0] if branch_ids else None

    meta: Dict[str, Any] = {
        "primary_branch_id": primary,
        "primary_branch_name": _branch_name(branches, primary) if primary else None,
        "requested_date_start": date_start,
        "requested_date_end": date_end,
        "strategy": "primary",
        "fallback_used": None,
    }

    def tag_results(xs: List[Dict[str, Any]], tier: str, minutes_map: Dict[str, int] = None):
        out = []
        for x in xs:
            x = dict(x)
            x["suggestion_tier"] = tier
            if minutes_map and x.get("branch_id") in minutes_map:
                x["drive_minutes"] = minutes_map[x["branch_id"]]
            out.append(x)
        return out

    # 1) Primary branch first (if provided)
    if primary:
        primary_results = _search_sessions(date_start, date_end, [primary], buckets, tags, has_spots, limit)
        primary_results = tag_results(primary_results, "primary")
    else:
        # no branch constraint -> behave like original search
        primary_results = _search_sessions(date_start, date_end, None, buckets, tags, has_spots, limit)
        primary_results = tag_results(primary_results, "primary")

    results = list(primary_results)
    meta["primary_count"] = len(primary_results)

    # Decide whether to expand (not pushy)
    thin = len(results) <= 1
    none = len(results) == 0

    # 2) Other day at same branch (only if single-day request AND none)
    if primary and none and _is_single_day_range(date_start, date_end):
        from datetime import date, timedelta
        ds = date.fromisoformat(date_start)
        de = date.fromisoformat(date_end)
        ds2 = (ds - timedelta(days=3)).isoformat()
        de2 = (de + timedelta(days=3)).isoformat()
        alt = _search_sessions(ds2, de2, [primary], buckets, tags, has_spots, limit)
        alt = tag_results(alt, "other_day")
        # Keep only those NOT on the originally requested day (makes the "other day" claim true)
        alt = [x for x in alt if not (date_start <= (x.get("start_time","")[:10]) < date_end)]
        if alt:
            meta["strategy"] = "same_branch_other_day"
            meta["fallback_used"] = "same_branch_other_day"
            meta["other_day_window"] = {"date_start": ds2, "date_end": de2}
            take = alt[: max(0, limit - len(results))]
            results.extend(take)

    # 3) Nearby branches same day (only if still thin OR none)
    if primary and (len(results) == 0 or thin):
        prox = _load_branch_proximity()
        neigh = prox.get(primary, []) or []
        neigh = [x for x in neigh if isinstance(x, dict) and x.get("branch_id")]
        # take up to 3 nearest
        neigh = sorted(neigh, key=lambda x: int(x.get("minutes", 999)))[:3]
        neigh_ids = [x["branch_id"] for x in neigh]
        minutes_map = {x["branch_id"]: int(x.get("minutes", 0)) for x in neigh if x.get("minutes") is not None}

        if neigh_ids:
            near = _search_sessions(date_start, date_end, neigh_ids, buckets, tags, has_spots, limit)
            near = tag_results(near, "nearby", minutes_map=minutes_map)

            if near:
                # Only mark strategy if we actually used nearby results
                meta["strategy"] = "nearby_same_day" if meta["strategy"] == "primary" else "mixed"
                meta["fallback_used"] = meta["fallback_used"] or "nearby_same_day"
                meta["nearby_branches"] = [
                    {"branch_id": x["branch_id"], "branch_name": _branch_name(branches, x["branch_id"]), "minutes": int(x.get("minutes", 0))}
                    for x in neigh
                ]

                take = near[: max(0, limit - len(results))]
                results.extend(take)

    # Final trim + counts
    results = results[:limit]
    meta["total"] = len(results)
    meta["tiers"] = {
        "primary": sum(1 for x in results if x.get("suggestion_tier") == "primary"),
        "other_day": sum(1 for x in results if x.get("suggestion_tier") == "other_day"),
        "nearby": sum(1 for x in results if x.get("suggestion_tier") == "nearby"),
    }
    return results, meta

def _enroll_member(session_id: str, member_id: str = "demo_member") -> Dict[str, Any]:
    c = conn()
    cur = c.cursor()

    row = cur.execute(
        """
        SELECT s.capacity, e.enrolled
        FROM sessions s
        JOIN enrollments e ON e.session_id = s.id
        WHERE s.id = ? AND s.status='scheduled'
        """,
        (session_id,),
    ).fetchone()
    if not row:
        c.close()
        raise HTTPException(status_code=404, detail="session not found")

    capacity = int(row["capacity"])
    enrolled = int(row["enrolled"])
    remaining = capacity - enrolled

    exists = cur.execute(
        "SELECT 1 FROM member_enrollments WHERE session_id=? AND member_id=?",
        (session_id, member_id),
    ).fetchone()
    if exists:
        c.close()
        return {"ok": True, "already_enrolled": True, "session_id": session_id}

    if remaining <= 0:
        c.close()
        raise HTTPException(status_code=409, detail="class is full")

    now = _now_iso()
    cur.execute(
        "INSERT INTO member_enrollments(session_id, member_id, created_at) VALUES (?,?,?)",
        (session_id, member_id, now),
    )
    cur.execute(
        "UPDATE enrollments SET enrolled = enrolled + 1, updated_at=? WHERE session_id=?",
        (now, session_id),
    )
    c.commit()

    row2 = cur.execute(
        """
        SELECT s.capacity, e.enrolled
        FROM sessions s
        JOIN enrollments e ON e.session_id = s.id
        WHERE s.id = ?
        """,
        (session_id,),
    ).fetchone()
    c.close()

    capacity2 = int(row2["capacity"])
    enrolled2 = int(row2["enrolled"])
    remaining2 = capacity2 - enrolled2
    return {
        "ok": True,
        "already_enrolled": False,
        "session_id": session_id,
        "capacity": capacity2,
        "enrolled": enrolled2,
        "remaining": remaining2,
        "availability_color": availability_color(enrolled2, capacity2),
    }

class UIContext(BaseModel):
    """
    UI context from the frontend. Keep this model purely declarative.
    Default-branch and branch-resolution logic belongs in `chat()`.
    """
    selected_branch_ids: list[str] = Field(default_factory=list)
    selected_buckets: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    only_has_spots: bool = True
    member_id: str | None = None
    user_group: str | None = None  # "member" or "front_desk"
class ChatRequest(BaseModel):
    session_id: str = "demo"
    message: str
    ui_context: UIContext = Field(default_factory=UIContext)

class ChatResponse(BaseModel):
    assistant_message: str
    follow_up_question: Optional[str] = None
    suggested_sessions: List[Dict[str, Any]] = Field(default_factory=list)

def _planner_prompt(branches: List[Dict[str, Any]], req: ChatRequest) -> List[Dict[str, str]]:
    start_week, end_week = _week_range_from_now()
    ui = req.ui_context.model_dump()
    last = LAST_SUGGESTIONS.get(req.session_id, [])[:5]

    system = f"""
You are Olivia, a YMCA schedule assistant. Return ONLY JSON.

Today's datetime: {_now_iso()}
Default "this week": {start_week}..{end_week}

Branches (use exact ids):
{json.dumps(branches, indent=2)}

UI context:
{json.dumps(ui, indent=2)}

Recent suggested options:
{json.dumps(last, indent=2)}

Pick ONE action:
- "find_sessions"
- "enroll"
- "clarify"

Schema:
{{
  "action": "find_sessions" | "enroll" | "clarify",
  "params": {{
    "date_start": "YYYY-MM-DD or null",
    "date_end": "YYYY-MM-DD or null",
    "branch_ids": ["branch_id"] or null,
    "buckets": ["swim","gym","sports","kids","run","cardio","strength","mind body","water fitness","lap swimming","open swim"] or null,
    "tags": ["hiit","yoga","swim", ...] or null,
    "has_spots": true/false,
    "limit": 1-5
  }},
  "enroll": {{
    "session_id": "string or null",
    "option": 1-5 or null,
    "member_id": "string"
  }},
  "follow_up_question": "string or null"
}}

Rules:
- If user says “my Y” and UI has no selected_branch_ids and you can't infer a branch confidently, use action="clarify".
- For enroll, use option if user says “option 2”.
"""
    return [{"role": "system", "content": system.strip()}, {"role": "user", "content": req.message.strip()}]

def _infer_date_range_from_message(message: str):
    """
    Return (date_start, date_end) as YYYY-MM-DD strings.
    date_end is treated as an exclusive bound (start + 1 day for single-day queries).
    """
    if not message:
        return None

    msg = message.lower()

    # quick phrases
    if "today" in msg:
        d = date.today()
        return (d.isoformat(), (d + timedelta(days=1)).isoformat())
    if "tomorrow" in msg:
        d = date.today() + timedelta(days=1)
        return (d.isoformat(), (d + timedelta(days=1)).isoformat())

    # this week / next week (Mon-Sun windows)
    if "next week" in msg:
        d = date.today()
        # next week's Monday
        days_to_mon = (0 - d.weekday()) % 7
        next_mon = d + timedelta(days=days_to_mon or 7)
        start = next_mon
        end = start + timedelta(days=7)
        return (start.isoformat(), end.isoformat())

    if "this week" in msg:
        d = date.today()
        start = d - timedelta(days=d.weekday())  # Monday
        end = start + timedelta(days=7)
        return (start.isoformat(), end.isoformat())

    # weekday parsing (handles "next thursday", "thursday", etc.)
    wd_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    # find any weekday token
    tokens = sorted(wd_map.keys(), key=len, reverse=True)
    found = None
    for t in tokens:
        if re.search(r"\b" + re.escape(t) + r"\b", msg):
            found = t
            break
    if not found:
        return None

    target = wd_map[found]
    d = date.today()
    days_ahead = (target - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # "Thursday" on a Thursday => next week's Thursday by default
    target_date = d + timedelta(days=days_ahead)

    # If phrase explicitly says "this <weekday>", allow same-week upcoming (including 0 days ahead)
    if re.search(r"\bthis\s+" + re.escape(found) + r"\b", msg):
        days_ahead2 = (target - d.weekday()) % 7
        target_date = d + timedelta(days=days_ahead2)

    start = target_date
    end = start + timedelta(days=1)
    return (start.isoformat(), end.isoformat())



def _build_suggestion_preface(req: ChatRequest, search_meta: Dict[str, Any], suggested: List[Dict[str, Any]]) -> str:
    primary_name = (search_meta or {}).get('primary_branch_name') or 'your Y'
    buckets = getattr(req.ui_context, 'selected_buckets', None) or []
    bucket_txt = (buckets[0] if buckets else 'classes').replace('_',' ').title()
    if not suggested:
        return f"I’m not seeing any {bucket_txt} sessions for {primary_name} in the current schedule. If you’d like, I can widen the date range or check nearby Ys." 
    return f"Here are the best matches I found at {primary_name}:"


def _build_options_header(search_meta: Dict[str, Any], suggested: List[Dict[str, Any]]) -> str:
    if not suggested:
        return ""
    tiers = (search_meta or {}).get("tiers") or {}
    primary_name = (search_meta or {}).get("primary_branch_name") or "your Y"
    primary_ct = int(tiers.get("primary", 0) or 0)
    other_ct = int(tiers.get("other_day", 0) or 0)
    near_ct  = int(tiers.get("nearby", 0) or 0)

    near_example = next((x for x in suggested if x.get("suggestion_tier") == "nearby" and x.get("drive_minutes")), None)
    near_branch  = (near_example or {}).get("branch_name")
    near_min     = (near_example or {}).get("drive_minutes")

    if primary_ct > 0 and other_ct == 0 and near_ct == 0:
        return f"Here are the top options at {primary_name}:"
    if primary_ct == 0 and other_ct > 0 and near_ct == 0:
        return f"I didn’t see anything on that day at {primary_name}, but there are a few options on other days at your Y:"
    if primary_ct == 0 and near_ct > 0:
        if near_branch and near_min:
            return f"I didn’t see anything on that day at {primary_name}, but {near_branch} is about ~{near_min} minutes away and has a few options:"
        return f"I didn’t see anything on that day at {primary_name}, but a nearby Y has a few options:"
    if primary_ct > 0 and (other_ct > 0 or near_ct > 0):
        if near_branch and near_min:
            return f"I found options at {primary_name}. If you’re open to nearby Ys too, {near_branch} is ~{near_min} minutes away and also has options:"
        return f"I found options at {primary_name}. If you’d like, I can also check nearby Ys or other days."
    return f"Here are the top options I found:" 

def _narrator_prompt(req: ChatRequest, tool_result: Dict[str, Any]) -> List[Dict[str, str]]:
    system = """
Return ONLY JSON:
{"assistant_message":"..."}
Keep it short. If listing sessions, label as options 1..N and include open spots.
IMPORTANT: Do NOT change any numbers (capacity/enrolled/remaining). Copy them exactly from the provided suggested_sessions/tool payload. Do not recalculate.
If tool payload includes search_meta, be friendly and human:
- Always prioritize options at the member’s primary branch first.
- If none on the requested day, gently mention options on other days at their Y (not pushy).
- If suggesting nearby branches, mention approx drive minutes ONLY if provided (drive_minutes) and keep tone light.
- Ask permission before expanding further if you already provided some options.
"""
    return [{"role": "system", "content": system.strip()},
            {"role": "user", "content": f"User: {req.message}\n\nTool result:\n{json.dumps(tool_result)}"}]


def _match_branch_id(branches: list, text: str):
    """Best-effort branch matcher from free text (name/aliases/substring)."""
    if not text:
        return None
    t = text.strip().lower()
    if not t:
        return None
    # exact/alias match
    for b in branches or []:
        bid = (b.get("id") if isinstance(b, dict) else None)
        name = (b.get("name") if isinstance(b, dict) else None) or (b.get("branch_name") if isinstance(b, dict) else None) or ""
        aliases = (b.get("aliases") if isinstance(b, dict) else None) or []
        name_l = str(name).lower()
        if t == name_l:
            return bid
        for a in aliases:
            if t == str(a).lower():
                return bid
    # substring/token match (e.g., "campbell county")
    for b in branches or []:
        bid = (b.get("id") if isinstance(b, dict) else None)
        name = (b.get("name") if isinstance(b, dict) else None) or (b.get("branch_name") if isinstance(b, dict) else None) or ""
        aliases = (b.get("aliases") if isinstance(b, dict) else None) or []
        hay = " ".join([str(name)] + [str(a) for a in aliases]).lower()
        if t in hay:
            return bid
    return None


def _bucket_label(bucket: str) -> str:
    m = {
        "kids_club": "Kids Club",
        "mind_body": "Mind & Body",
        "strength": "Strength",
        "run": "Run",
        "sports": "Sports",
        "gym": "Gym",
        "swim": "Swim",
    }
    b = (bucket or "").strip().lower()
    return m.get(b, (bucket or "").replace("_", " ").title() or "Classes")

def _pretty_day(iso_date: str) -> str:
    # iso_date: YYYY-MM-DD
    try:
        from datetime import date as _date
        d = _date.fromisoformat(iso_date)
        return d.strftime("%a %b %d")
    except Exception:
        return iso_date

def _pretty_time(iso_dt: str) -> str:
    # iso_dt: 2026-01-22T06:10:00-05:00
    try:
        from datetime import datetime as _dt
        d = _dt.fromisoformat(iso_dt)
        return d.strftime("%a %b %d %I:%M %p").replace(" 0", " ")
    except Exception:
        return iso_dt

def _branch_name_map(branches):
    return {b.get("id"): b.get("name") for b in (branches or [])}

def _suggest_sessions_tiered(
    *,
    branches,
    date_start: str,
    date_end: str,
    home_branch_id: str | None,
    buckets,
    tags,
    has_spots: bool,
    limit: int,
):
    """
    Returns (suggested_sessions, suggestion_context)
    suggestion_tier: primary | other_day | nearby_branch | nearby_other_day
    """
    from datetime import date, timedelta

    bmap = _branch_name_map(branches)
    home_name = bmap.get(home_branch_id, home_branch_id) if home_branch_id else None

    ctx = {
        "home_branch_id": home_branch_id,
        "home_branch_name": home_name,
        "target_date_start": date_start,
        "target_date_end": date_end,
        "tier_used": "none",
    }

    # 1) primary: same day at home branch
    if home_branch_id:
        primary = _search_sessions(date_start, date_end, [home_branch_id], buckets, tags, has_spots, limit)
    else:
        primary = _search_sessions(date_start, date_end, None, buckets, tags, has_spots, limit)

    if primary:
        for s in primary:
            s["suggestion_tier"] = "primary"
            s.pop("drive_minutes", None)
        ctx["tier_used"] = "primary"
        return primary, ctx

    single_day = (date_start == date_end)
    if not home_branch_id:
        return [], ctx

    # helper: parse target date
    try:
        target = date.fromisoformat(date_start)
    except Exception:
        target = None

    # 2) other_day at home branch (only makes sense for single-day asks)
    if single_day and target:
        w_start = (target - timedelta(days=3)).isoformat()
        w_end = (target + timedelta(days=7)).isoformat()
        other = _search_sessions(w_start, w_end, [home_branch_id], buckets, tags, has_spots, max(limit, 8))
        other = [x for x in other if (x.get("start_time","")[:10] != date_start)]
        if other:
            for s in other:
                s["suggestion_tier"] = "other_day"
                s.pop("drive_minutes", None)
            ctx.update({"tier_used": "other_day", "widened_start": w_start, "widened_end": w_end})
            return other[:limit], ctx

    # 3) nearby branches same day
    prox = _load_branch_proximity()
    neighbors = prox.get(home_branch_id, []) or []
    gathered = []
    for nb in neighbors:
        nb_id = nb.get("branch_id") or nb.get("id")
        mins = nb.get("drive_minutes") or nb.get("minutes")
        if not nb_id:
            continue
        res = _search_sessions(date_start, date_end, [nb_id], buckets, tags, has_spots, max(limit, 8))
        for s in res:
            s["suggestion_tier"] = "nearby_branch"
            if mins is not None:
                try:
                    s["drive_minutes"] = int(mins)
                except Exception:
                    s["drive_minutes"] = mins
            gathered.append(s)

    if gathered:
        gathered.sort(key=lambda x: (x.get("drive_minutes", 9999), x.get("start_time","")))
        ctx["tier_used"] = "nearby_branch"
        return gathered[:limit], ctx

    # 4) nearby branches other days
    if single_day and target and neighbors:
        w_start = (target - timedelta(days=3)).isoformat()
        w_end = (target + timedelta(days=7)).isoformat()
        gathered2 = []
        for nb in neighbors:
            nb_id = nb.get("branch_id") or nb.get("id")
            mins = nb.get("drive_minutes") or nb.get("minutes")
            if not nb_id:
                continue
            res = _search_sessions(w_start, w_end, [nb_id], buckets, tags, has_spots, max(limit, 12))
            res = [x for x in res if (x.get("start_time","")[:10] != date_start)]
            for s in res:
                s["suggestion_tier"] = "nearby_other_day"
                if mins is not None:
                    try:
                        s["drive_minutes"] = int(mins)
                    except Exception:
                        s["drive_minutes"] = mins
                gathered2.append(s)
        if gathered2:
            gathered2.sort(key=lambda x: (x.get("drive_minutes", 9999), x.get("start_time","")))
            ctx.update({"tier_used": "nearby_other_day", "widened_start": w_start, "widened_end": w_end})
            return gathered2[:limit], ctx

    return [], ctx

def _build_suggestions_message(req, suggested, suggestion_context, branches):
    # Friendly, human-ish, not pushy. Deterministic.
    bmap = _branch_name_map(branches)
    home_id = (suggestion_context or {}).get("home_branch_id") or (getattr(req, "ui_context", None) and req.ui_context.selected_branch_ids[:1] or [None])[0]
    home_name = (suggestion_context or {}).get("home_branch_name") or bmap.get(home_id, home_id) or "your Y"

    target = (suggestion_context or {}).get("target_date_start") or ""
    tier = (suggestion_context or {}).get("tier_used") or "none"

    # bucket label
    bucket = None
    try:
        bucket = (req.ui_context.selected_buckets or [None])[0]
    except Exception:
        bucket = None
    bucket_name = _bucket_label(bucket or "")

    if not suggested:
        if target:
            return f"I’m not seeing any {bucket_name} sessions for {home_name} on {_pretty_day(target)}. If you’d like, I can widen the date range or check nearby Ys."
        return f"I’m not seeing any matching {bucket_name} sessions right now. Want me to widen the date range or check nearby Ys?"

    # intro line based on tier
    if tier == "primary":
        intro = f"Here are the top options at {home_name}:"
    elif tier == "other_day":
        intro = f"I don’t see any {bucket_name} sessions at {home_name} on {_pretty_day(target)}, but here are a few coming up at your Y:"
    elif tier == "nearby_branch":
        intro = f"I don’t see any {bucket_name} sessions at {home_name} on {_pretty_day(target)}. The closest options that day are:"
    elif tier == "nearby_other_day":
        intro = f"I don’t see any {bucket_name} sessions at {home_name} on {_pretty_day(target)}. Here are a few nearby options on other days:"
    else:
        intro = "Here are the top options:"

    # numbered list
    lines = [intro]
    for i,s in enumerate(suggested, 1):
        when = _pretty_time(s.get("start_time",""))
        bname = s.get("branch_name") or bmap.get(s.get("branch_id")) or ""
        rem = s.get("remaining")
        col = s.get("availability_color")
        mins = s.get("drive_minutes")
        drive = f" (~{mins} min drive)" if mins is not None else ""
        place = f"{bname}{drive}".strip()
        lines.append(f"{i}) {s.get('class_name')} @ {place} {when} — {rem} spots ({col})")

    return "\n".join(lines)

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    branches = _load_branches()

    # resolve branch from user text OR apply defaults when none selected
    if not (req.ui_context.selected_branch_ids or []):
        bid = _match_branch_id_from_text(branches, req.message)
        if bid:
            req.ui_context.selected_branch_ids = [bid]
        else:
            defaults = _default_branch_ids(req)
            if defaults:
                req.ui_context.selected_branch_ids = defaults

    suggestion_note = ""

    hist = CHAT_HISTORY.get(req.session_id, [])
    is_new_session = len(hist) == 0


    # branch reply follow-up: if we just asked "Which branch is your Y?", treat this message as the branch,
    # then re-run the prior question with that branch selected.
    if not (req.ui_context.selected_branch_ids or []):
        ask_idx = None
        for _i in range(len(hist) - 2, -1, -1):  # ignore current user msg at end
            m = hist[_i]
            if m.get("role") == "assistant" and "Which branch is" in (m.get("content", "")):
                ask_idx = _i
                break

        if ask_idx is not None:
            prior_q = None
            for _j in range(ask_idx - 1, -1, -1):
                if hist[_j].get("role") == "user":
                    prior_q = hist[_j].get("content", "")
                    break

            bid = _match_branch_id(branches, req.message)
            if bid:
                try:
                    ui2 = req.ui_context.model_copy(deep=True)
                except Exception:
                    ui2 = req.ui_context
                try:
                    ui2.selected_branch_ids = [bid]
                except Exception:
                    pass

                # Re-run the prior question, but keep this user message in history as the branch reply.
                if prior_q:
                    req = ChatRequest(session_id=req.session_id, message=prior_q, ui_context=ui2)
                else:
                    req = ChatRequest(session_id=req.session_id, message=req.message, ui_context=ui2)
            else:
                q = "Sorry — which YMCA branch should I use? (For example: “Campbell County YMCA”.)"
                hist.append({"role": "assistant", "content": q})
                CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
                return ChatResponse(assistant_message=q, follow_up_question=q, suggested_sessions=[])

    def _maybe_greet(msg: str) -> str:
        if is_new_session and msg and not msg.startswith(OLIVIA_GREETING):
            return f"{OLIVIA_GREETING}\n\n{msg}"
        return msg

    hist.append({"role": "user", "content": req.message})
    CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]


    # Pending follow-up: user is answering the branch question (avoid LLM planner here)
    pending = PENDING_CONTEXT.get(req.session_id)
    if pending and pending.get("type") == "awaiting_branch":
        branch_id = _resolve_branch_id_from_text(branches, req.message)
        if not branch_id:
            q = "Which branch should I use? (You can say e.g. “Blue Ash YMCA”.)"
            hist.append({"role": "assistant", "content": q})
            CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
            return ChatResponse(assistant_message=q, follow_up_question=q)

        # consume pending + run the original search against the chosen branch
        orig = pending.get("original_message") or req.message
        date_start = pending.get("date_start") or _week_range_from_now()[0]
        date_end = pending.get("date_end") or _week_range_from_now()[1]
        buckets = pending.get("buckets")
        tags = pending.get("tags")
        has_spots = bool(pending.get("has_spots", True))
        limit = int(pending.get("limit", 5))

        PENDING_CONTEXT.pop(req.session_id, None)

        # Prefer intelligent policy if present, else basic search
        try:
            suggested = _intelligent_suggest_sessions(
                date_start=date_start,
                date_end=date_end,
                primary_branch_id=branch_id,
                buckets=buckets,
                tags=tags,
                has_spots=has_spots,
                limit=limit,
            )
        except NameError:
            suggested = _search_sessions(date_start, date_end, [branch_id], buckets, tags, has_spots, limit)

        # Update LAST_SUGGESTIONS for enroll-by-option
        LAST_SUGGESTIONS[req.session_id] = [
            {"option": i + 1, "session_id": s["session_id"], "label": f'{s["class_name"]} @ {s["branch_name"]} {s["start_time"]}'}
            for i, s in enumerate(suggested)
        ]

        # Deterministic friendly message (avoid narrator LLM here)
        bname = next((b.get("name") for b in branches if b.get("id") == branch_id), "your Y")
        if suggested:
            lines_ = [f"Here are the top options at {bname}:"]
            for i, ss in enumerate(suggested, 1):
                lines_.append(f"{i}) {ss.get('class_name')} {ss.get('start_time')} — {ss.get('remaining')} spots ({ss.get('availability_color')})")
            assistant_message = "\n".join(lines_)
        else:
            assistant_message = f"I’m not seeing any matches at {bname} for that request. Want me to check nearby Ys or a different day?"

        hist.append({"role": "assistant", "content": assistant_message})
        CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
        return ChatResponse(assistant_message=assistant_message, suggested_sessions=suggested)


    # Quick-path: handle follow-ups like "Sign me up for option 1" using LAST_SUGGESTIONS
    msg_l = (req.message or "").lower()
    opt_m = re.search(r"\boption\s*(\d+)\b", msg_l)
    if opt_m:
        opt = int(opt_m.group(1))
        last = LAST_SUGGESTIONS.get(req.session_id, [])
        if any(x.get("option") == opt for x in last):
            plan = {"action": "enroll", "enroll": {"option": opt, "member_id": "demo_member"}}
        else:
            plan = {"action": "clarify", "follow_up_question": "I don't have recent options yet. Ask for availability first."}
    else:
        pending = PENDING_CONTEXT.get(req.session_id)
        if pending:
            ui_branch_ids = req.ui_context.selected_branch_ids or []
            branch_ids = ui_branch_ids if ui_branch_ids else None
            if not branch_ids:
                bid = _match_branch_id(branches, req.message)
                branch_ids = [bid] if bid else None
            if branch_ids:
                merged = dict(pending)
                merged["branch_ids"] = branch_ids
                # also keep UI-selected buckets as hard constraint if present
                if req.ui_context.selected_buckets:
                    merged["buckets"] = req.ui_context.selected_buckets
                merged["has_spots"] = bool(getattr(req.ui_context, "only_has_spots", merged.get("has_spots", True)))
                plan = {"action": "find_sessions", "params": merged}
                PENDING_CONTEXT.pop(req.session_id, None)
            else:
                plan = ollama_chat_json(_planner_prompt(branches, req))
        else:
            plan = ollama_chat_json(_planner_prompt(branches, req))

    # --- Harden planner output so demos never 400 on missing/invalid action ---
    if not isinstance(plan, dict):
        plan = {}

    action = (plan.get("action") or "").strip().lower()
    follow_up = plan.get("follow_up_question")

    # Default if planner omitted action
    if not action:
        msg_l = (req.message or "").lower()
        sel_branches = getattr(req.ui_context, "selected_branch_ids", None) or []
        sel_buckets = getattr(req.ui_context, "selected_buckets", None) or []

        enroll_intent = any(k in msg_l for k in ["sign me up", "enroll", "register", "book", "reserve"])
        query_intent = any(k in msg_l for k in ["availability", "available", "schedule", "classes", "calendar", "open gym", "hours", "open", "swim", "yoga", "hiit"])
        has_ui_context = bool(sel_branches or sel_buckets)

        if enroll_intent:
            e = plan.get("enroll") or {}
            has_target = bool(e.get("session_id") or e.get("option"))
            action = "enroll" if has_target else "clarify"
            if not has_target and not follow_up:
                follow_up = "Which class should I enroll you in? Say “option 1” (or click Enroll)."
        elif query_intent or has_ui_context:
            action = "find_sessions"
        else:
            action = "clarify"
            if not follow_up:
                follow_up = "Do you want class availability, hours, or to enroll in a session?"

        plan["action"] = action

    # Force invalid action → clarify (never 400)
    if action not in ("clarify", "find_sessions", "enroll"):
        action = "clarify"
        if not follow_up:
            follow_up = "Do you want class availability, hours, or to enroll in a session?"
        plan["action"] = action

    if action == "clarify" or follow_up:
        # stash pending intent for branch follow-up (preserve date/buckets)
        try:
            inferred = _infer_date_range_from_message(req.message)
        except Exception:
            inferred = None
        if inferred:
            ds, de = inferred
        else:
            ds, de = _week_range_from_now()
        PENDING_CONTEXT[req.session_id] = {
            "date_start": ds,
            "date_end": de,
            "buckets": (req.ui_context.selected_buckets or None),
            "tags": None,
            "has_spots": bool(getattr(req.ui_context, "only_has_spots", True)),
            "limit": 6,
        }
        assistant = follow_up or "Which branch should I use?"
        assistant = _maybe_greet(assistant)
        hist.append({"role": "assistant", "content": assistant})
        CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
        return ChatResponse(assistant_message=assistant, follow_up_question=assistant)

    suggested: List[Dict[str, Any]] = []
    tool_payload: Dict[str, Any] = {"action": action}

    if action == "find_sessions":
        p = plan.get("params") or {}
        date_start = p.get("date_start")
        date_end = p.get("date_end")
        if not date_start and not date_end:
            inferred = _infer_date_range_from_message(req.message)
            if inferred:
                date_start, date_end = inferred
        if not date_start or not date_end:
            ws, we = _week_range_from_now()
            date_start = date_start or ws
            date_end = date_end or we
        ui_branch_ids = req.ui_context.selected_branch_ids or None
        branch_ids = ui_branch_ids if ui_branch_ids else (p.get("branch_ids") or None)
        if branch_ids is None:
            branch_ids = req.ui_context.selected_branch_ids or None
            # apply defaults if still unset
            if not branch_ids:
                branch_ids = _default_branch_ids(req) or None
        ui_buckets = req.ui_context.selected_buckets or None
        buckets = ui_buckets if ui_buckets else (p.get("buckets") or None)
        if buckets is None:
            buckets = req.ui_context.selected_buckets or None
            buckets = _normalize_bucket_ids(buckets)
        tags = p.get("tags")
        has_spots = bool(p.get("has_spots", True))
        ui_only = getattr(req.ui_context, "only_has_spots", None)
        if ui_only is not None:
            has_spots = bool(ui_only)
        limit = int(p.get("limit", 5))

        if branch_ids is None and "my y" in req.message.lower():
            # remember the user's original request so the next message (branch name) can complete it deterministically
            PENDING_CONTEXT[req.session_id] = {
                "type": "awaiting_branch",
                "original_message": req.message,
                "date_start": date_start,
                "date_end": date_end,
                "buckets": buckets,
                "tags": tags,
                "has_spots": has_spots,
                "limit": limit,
            }

            q = "Which branch is “your Y”? (Pick one in the branch filters, or say e.g. “Blue Ash YMCA”.)"
            q = _maybe_greet(q)
            hist.append({"role": "assistant", "content": q})
            CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
            return ChatResponse(assistant_message=q, follow_up_question=q)

        suggested, search_meta = _search_sessions_with_fallback(date_start, date_end, branch_ids, buckets, tags, has_spots, limit, branches)

        LAST_SUGGESTIONS[req.session_id] = [
            {"option": i + 1, "session_id": s["session_id"], "label": f'{s["class_name"]} @ {s["branch_name"]} {s["start_time"]}'}
            for i, s in enumerate(suggested)
        ]

        if suggestion_note:
            tool_payload["suggestion_note"] = suggestion_note

        tool_payload.update({"date_start": date_start, "date_end": date_end, "suggested_sessions": suggested, "search_meta": search_meta})
        tool_payload["suggestion_preface"] = _build_suggestion_preface(req, search_meta, suggested)
        tool_payload["options_header"] = _build_options_header(search_meta, suggested)


        if not suggested:
            assistant_message = _maybe_greet(tool_payload.get("suggestion_preface") or "I couldn’t find any matching sessions.")
            hist.append({"role": "assistant", "content": assistant_message})
            CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
            return ChatResponse(assistant_message=assistant_message, suggested_sessions=[])

    elif action == "enroll":
        e = plan.get("enroll") or {}
        member_id = e.get("member_id") or "demo_member"
        session_id = e.get("session_id")
        option = e.get("option")

        if not session_id and option:
            last = LAST_SUGGESTIONS.get(req.session_id, [])
            match = next((x for x in last if x.get("option") == option), None)
            session_id = match.get("session_id") if match else None

        if not session_id:
            q = "Which class should I enroll you in? Say “option 1” (or click Enroll)."
            q = _maybe_greet(q)
            hist.append({"role": "assistant", "content": q})
            CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
            return ChatResponse(assistant_message=q, follow_up_question=q)

        tool_payload["enroll_result"] = _enroll_member(session_id=session_id, member_id=member_id)

    else:
        q = "Do you want class availability, hours, or to enroll in a session?"
        q = _maybe_greet(q)
        hist.append({"role": "assistant", "content": q})
        CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]
        return ChatResponse(assistant_message=q, follow_up_question=q)

    narrated = ollama_chat_json(_narrator_prompt(req, tool_payload))
    assistant_message = narrated.get("assistant_message") if isinstance(narrated, dict) else None
    hdr = tool_payload.get("options_header")
    if hdr and suggested and hdr not in (assistant_message or ""):
        if assistant_message and assistant_message.startswith(OLIVIA_GREETING):
            rest = assistant_message[len(OLIVIA_GREETING):].lstrip("\n ")
            assistant_message = f"{OLIVIA_GREETING}\n\n{hdr}" + (f"\n{rest}" if rest else "")
        else:
            assistant_message = f"{hdr}\n{assistant_message}" if assistant_message else hdr

    # If narrator returns empty/"Done" but we have tool results, render deterministically
    if (not assistant_message) or (assistant_message.strip().lower() in ("done", "done.")):
        if action == "find_sessions":
            if suggested:
                out = ["Here are the top options:"]
                for j, ss in enumerate(suggested, 1):
                    out.append(
                        f"{j}) {ss.get('class_name')} @ {ss.get('branch_name')} {ss.get('start_time')} — {ss.get('remaining')} spots ({ss.get('availability_color')})"
                    )
                assistant_message = "\n".join(out)
            else:
                assistant_message = "I couldn't find any matching sessions."
        elif action == "enroll":
            er = tool_payload.get("enroll_result") or {}
            rem = er.get("remaining")
            assistant_message = f"Enrolled. Remaining spots: {rem}." if rem is not None else "Enrolled."
        else:
            assistant_message = assistant_message or "Done."

    # prefix greeting once per new session
    if is_new_session:
        if assistant_message:
            if not assistant_message.startswith(OLIVIA_GREETING):
                assistant_message = f"{OLIVIA_GREETING}\n\n{assistant_message}"
        else:
            assistant_message = OLIVIA_GREETING

    hist.append({"role": "assistant", "content": assistant_message})
    CHAT_HISTORY[req.session_id] = hist[-MAX_HISTORY:]

    return ChatResponse(assistant_message=assistant_message, suggested_sessions=suggested)
