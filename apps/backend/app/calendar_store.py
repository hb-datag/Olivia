import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

BACKEND_DIR = Path(__file__).resolve().parents[1]         # .../apps/backend
DB_PATH = BACKEND_DIR / "data" / "olivia.db"
CONFIG_DIR = BACKEND_DIR.parents[1] / "configs"           # .../Olivia/configs

FACILITIES_PATH = CONFIG_DIR / "facilities.json"
CATALOG_PATH = CONFIG_DIR / "class_catalog.json"

def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db() -> None:
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS branches (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS classes (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      bucket TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      default_location TEXT NOT NULL,
      default_duration_min INTEGER NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      class_id TEXT NOT NULL,
      branch_id TEXT NOT NULL,
      start_ts TEXT NOT NULL,
      end_ts TEXT NOT NULL,
      location TEXT NOT NULL,
      instructor TEXT NOT NULL,
      capacity INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'scheduled'
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS enrollments (
      session_id TEXT PRIMARY KEY,
      enrolled INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL
    );
    """)

    # per-member enrollments (prevents enrolling same member twice)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS member_enrollments (
      session_id TEXT NOT NULL,
      member_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY (session_id, member_id)
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_branch_start ON sessions(branch_id, start_ts);")

    c.commit()
    c.close()

def seed(seed: int = 42, days: int = 21) -> None:
    random.seed(seed)
    c = conn()
    cur = c.cursor()

    def _count(table: str) -> int:
        return int(c.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

    if _count("branches") == 0:
        facilities = json.loads(FACILITIES_PATH.read_text())
        for b in facilities["branches"]:
            cur.execute("INSERT OR IGNORE INTO branches(id,name) VALUES (?,?)", (b["id"], b["name"]))

    if _count("classes") == 0:
        cat = json.loads(CATALOG_PATH.read_text())
        for cl in cat["classes"]:
            cur.execute(
                "INSERT OR IGNORE INTO classes(id,name,bucket,tags_json,default_location,default_duration_min) VALUES (?,?,?,?,?,?)",
                (
                    cl["id"], cl["name"], cl["bucket"], json.dumps(cl["tags"]),
                    cl["default_location"], int(cl["default_duration_min"])
                )
            )

    if _count("sessions") == 0:
        branches = c.execute("SELECT id,name FROM branches").fetchall()
        classes = c.execute("SELECT * FROM classes").fetchall()

        slots = [
            (5, 0), (6, 0), (6, 10), (6, 40),
            (7, 0), (8, 0), (8, 45), (9, 0),
            (10, 15), (11, 30), (16, 30), (17, 30), (18, 40)
        ]

        today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)

        for d in range(days):
            day = today + timedelta(days=d)
            for b in branches:
                branch_id = b["id"]

                picks = []
                for _ in range(6):
                    picks.append(random.choice([cl for cl in classes if cl["bucket"] == "swim"] + [random.choice(classes)]))
                for _ in range(5):
                    picks.append(random.choice([cl for cl in classes if cl["bucket"] == "gym"]))
                for _ in range(3):
                    picks.append(random.choice([cl for cl in classes if cl["bucket"] in ("sports","kids")]))

                random.shuffle(picks)

                for i, cl in enumerate(picks[:12]):
                    hh, mm = slots[i % len(slots)]
                    start = day.replace(hour=hh, minute=mm)
                    dur = int(cl["default_duration_min"])
                    end = start + timedelta(minutes=dur)

                    session_id = f"s_{branch_id}_{start.strftime('%Y%m%d_%H%M')}_{cl['id']}"
                    cap = random.choice([8, 12, 16, 20, 25, 30, 40, 70])

                    roll = random.random()
                    if roll < 0.10:
                        enrolled = cap
                    elif roll < 0.30:
                        enrolled = int(cap * random.uniform(0.80, 0.99))
                    else:
                        enrolled = int(cap * random.uniform(0.10, 0.75))

                    instructor = random.choice(["Staff","Sarah C.","Tabatha W.","Bridget R.","Jen M.","Connie S.","Amy W.","Elizabeth W.","Alyona G."])

                    cur.execute(
                        "INSERT OR IGNORE INTO sessions(id,class_id,branch_id,start_ts,end_ts,location,instructor,capacity,status) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            session_id, cl["id"], branch_id,
                            start.isoformat(), end.isoformat(),
                            cl["default_location"], instructor, cap, "scheduled"
                        )
                    )
                    cur.execute(
                        "INSERT OR IGNORE INTO enrollments(session_id,enrolled,updated_at) VALUES (?,?,?)",
                        (session_id, enrolled, datetime.now(TZ).isoformat())
                    )

    c.commit()
    c.close()

def availability_color(enrolled: int, capacity: int) -> str:
    # YOUR RULES:
    # amber >= 80% full, red = 100% full
    if capacity <= 0:
        return "red"
    pct_full = enrolled / capacity
    if pct_full >= 1.0:
        return "red"
    if pct_full >= 0.80:
        return "amber"
    return "green"
