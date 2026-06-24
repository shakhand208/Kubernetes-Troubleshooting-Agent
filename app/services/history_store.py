from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.core.models import InvestigationState


class HistoryStore:
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._lock = Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    def list_history(self) -> list[dict]:
        with self._lock:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw or "[]")
            if not isinstance(data, list):
                return []
            return data

    def append(self, state: InvestigationState) -> None:
        with self._lock:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw or "[]")
            if not isinstance(data, list):
                data = []
            data.insert(0, state.model_dump())
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
