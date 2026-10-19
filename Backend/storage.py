import json
import os
import tempfile
import threading
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data.json"
DATA_TEMPLATE_PATH = Path(__file__).parent / "data.example.json"
_LOCK = threading.RLock()


def load() -> dict:
    with _LOCK:
        if not DATA_PATH.exists():
            with open(DATA_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                _save(json.load(f))
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for key, default in (("users", []), ("sessions", {}), ("analyses", {}), ("decisions", {})):
            if key not in data:
                data[key] = default
                changed = True
        for case in data.get("cases", []):
            if "owner_id" not in case:
                case["owner_id"] = None
                case["legacy_seed"] = True
                changed = True
        if changed:
            _save(data)
        return data


def save(data: dict) -> None:
    """Write to a temp file first, then replace, so the file is never half-written."""
    with _LOCK:
        _save(data)


def _save(data: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=DATA_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, DATA_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_lock():
    """Serialize read/modify/write sections in this process."""
    return _LOCK


def get_case(data: dict, case_id: str):
    return next((c for c in data["cases"] if c["id"] == case_id), None)


def get_listing(data: dict, listing_id: str):
    return next((l for l in data["listings"] if l["id"] == listing_id), None)
