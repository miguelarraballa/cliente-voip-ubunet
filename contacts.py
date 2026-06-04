import csv
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app_paths import USER_DATA_DIR
_SETTINGS_FILE = USER_DATA_DIR / ".voip_settings.json"


def _read_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_settings(data: dict) -> None:
    try:
        existing = _read_settings()
        existing.update(data)
        _SETTINGS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass


@dataclass
class Contact:
    name: str
    extension: str


class ContactManager:
    def __init__(self):
        self.contacts: List[Contact] = []

    def last_imported_path(self) -> Optional[str]:
        """Devuelve la ruta del último archivo importado, o None."""
        return _read_settings().get("contacts_file")

    def load_from_file(self, path: str) -> int:
        if path.lower().endswith(".csv"):
            count = self._load_csv(path)
        elif path.lower().endswith(".xml"):
            count = self._load_xml(path)
        else:
            raise ValueError(f"Formato no soportado: {path}. Usa CSV o XML.")
        _write_settings({"contacts_file": path})
        return count

    def _load_csv(self, path: str) -> int:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.contacts = [
                Contact(
                    name=row.get("name", row.get("nombre", "")).strip(),
                    extension=row.get("extension", row.get("ext", "")).strip(),
                )
                for row in reader
                if row.get("name", row.get("nombre", "")).strip()
                and row.get("extension", row.get("ext", "")).strip()
            ]
        return len(self.contacts)

    def _load_xml(self, path: str) -> int:
        tree = ET.parse(path)
        root = tree.getroot()
        contacts = []
        for el in root.iter("contact"):
            name = (el.get("name") or el.get("nombre") or el.findtext("name") or el.findtext("nombre") or "").strip()
            ext = (el.get("extension") or el.get("ext") or el.findtext("extension") or el.findtext("ext") or "").strip()
            if name and ext:
                contacts.append(Contact(name=name, extension=ext))
        self.contacts = contacts
        return len(self.contacts)

    def search(self, query: str) -> List[Contact]:
        if not query:
            return self.contacts
        q = query.lower()
        return [c for c in self.contacts if q in c.name.lower() or q in c.extension]

    def find_by_extension(self, number: str) -> Optional[Contact]:
        """Devuelve el contacto cuya extensión coincide con number (exacto o sufijo)."""
        if not number:
            return None
        for c in self.contacts:
            if c.extension == number:
                return c
            # Coincidencia parcial por sufijo para números con prefijo de país
            tail = min(len(c.extension), len(number), 7)
            if tail >= 4 and c.extension[-tail:] == number[-tail:]:
                return c
        return None
