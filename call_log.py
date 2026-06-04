"""
Historial de llamadas: entrantes, salientes y perdidas.
"""
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List

from app_paths import USER_DATA_DIR
_LOG_FILE = USER_DATA_DIR / ".call_log.json"
_MAX_ENTRIES = 1000

TYPE_ICONS = {
    "outgoing": "📞",
    "incoming": "📲",
    "missed":   "📵",
}
TYPE_LABELS = {
    "outgoing": "Saliente",
    "incoming": "Entrante",
    "missed":   "Perdida",
}


class CallEntry:
    __slots__ = ("type", "ts", "number", "name", "duration")

    def __init__(self, type_: str, ts: str, number: str,
                 name: Optional[str] = None, duration: Optional[int] = None):
        self.type     = type_
        self.ts       = ts        # "YYYY-MM-DD HH:MM:SS"
        self.number   = number
        self.name     = name
        self.duration = duration  # segundos; None para perdidas

    # ── Representación ────────────────────────────────────────────────────────

    @property
    def display_party(self) -> str:
        if self.name:
            return f"{self.name}  ({self.number})"
        return self.number

    @property
    def display_duration(self) -> str:
        if self.duration is None:
            return "—"
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"

    @property
    def display_ts(self) -> str:
        try:
            dt = datetime.strptime(self.ts, "%Y-%m-%d %H:%M:%S")
            today = date.today()
            if dt.date() == today:
                return f"Hoy {dt.strftime('%H:%M')}"
            if (today - dt.date()).days == 1:
                return f"Ayer {dt.strftime('%H:%M')}"
            return dt.strftime("%d/%m  %H:%M")
        except Exception:
            return self.ts

    # ── Serialización ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {"type": self.type, "ts": self.ts, "number": self.number,
                "name": self.name, "duration": self.duration}

    @classmethod
    def from_dict(cls, d: dict) -> "CallEntry":
        return cls(d["type"], d["ts"], d["number"],
                   d.get("name"), d.get("duration"))


class CallLog:
    def __init__(self):
        self._entries: List[CallEntry] = []
        self._load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            raw = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
            self._entries = [CallEntry.from_dict(d) for d in raw]
        except Exception:
            self._entries = []

    def _save(self):
        try:
            _LOG_FILE.write_text(
                json.dumps([e.to_dict() for e in self._entries], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── API pública ───────────────────────────────────────────────────────────

    def add(self, type_: str, number: str,
            name: Optional[str] = None,
            duration: Optional[int] = None) -> CallEntry:
        entry = CallEntry(
            type_=type_,
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            number=number,
            name=name,
            duration=duration,
        )
        self._entries.insert(0, entry)
        if len(self._entries) > _MAX_ENTRIES:
            self._entries = self._entries[:_MAX_ENTRIES]
        self._save()
        return entry

    def entries(self, limit: int = 200) -> List[CallEntry]:
        return self._entries[:limit]
