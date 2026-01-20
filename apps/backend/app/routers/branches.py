import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[4]   # ~/Olivia
CONFIG_DIR = ROOT_DIR / "configs"
FACILITIES_PATH = CONFIG_DIR / "facilities.json"

@router.get("/branches")
def list_branches():
    data = json.loads(FACILITIES_PATH.read_text())
    return {"branches": data["branches"]}
