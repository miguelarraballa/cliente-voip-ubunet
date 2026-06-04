import csv
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List


@dataclass
class Contact:
    name: str
    extension: str


class ContactManager:
    def __init__(self):
        self.contacts: List[Contact] = []

    def load_from_file(self, path: str) -> int:
        if path.lower().endswith(".csv"):
            return self._load_csv(path)
        elif path.lower().endswith(".xml"):
            return self._load_xml(path)
        raise ValueError(f"Formato no soportado: {path}. Usa CSV o XML.")

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
