from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

OLLAMA_URL = os.getenv("OLIVIA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLIVIA_OLLAMA_MODEL", "llama3.2:3b")
TIMEOUT_S = float(os.getenv("OLIVIA_OLLAMA_TIMEOUT_S", "120"))
DEFAULT_SEED = int(os.getenv("OLIVIA_OLLAMA_SEED", "42"))

DEFAULT_OPTIONS: Dict[str, Any] = {
    "temperature": float(os.getenv("OLIVIA_OLLAMA_TEMPERATURE", "0")),
    "top_p": float(os.getenv("OLIVIA_OLLAMA_TOP_P", "1")),
    "seed": DEFAULT_SEED,
    "num_predict": int(os.getenv("OLIVIA_OLLAMA_NUM_PREDICT", "256")),
}

def ollama_chat_json(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {**DEFAULT_OPTIONS, **(options or {})},
    }
    url = f"{OLLAMA_URL}/api/chat"
    with httpx.Client(timeout=TIMEOUT_S) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        return r.json()
