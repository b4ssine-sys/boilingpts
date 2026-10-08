"""Loader for strings.json, the single table of player-facing text."""
import json
import os

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strings.json")
KINDS = ("ui", "narrative")
STATUSES = ("draft", "approved")


class Strings:
    def __init__(self, entries):
        self._entries = entries
        self._validate()

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f)["strings"])

    def get(self, key, **fmt):
        """Look up a line. A missing key raises, so gaps show up in testing
        instead of shipping as blank text."""
        return self._entries[key]["text"].format(**fmt)

    def keys(self):
        return self._entries.keys()

    def entry(self, key):
        return self._entries[key]

    def _validate(self):
        for key, e in self._entries.items():
            if e.get("kind") not in KINDS:
                raise ValueError(f"{key}: kind must be one of {KINDS}")
            if e.get("status") not in STATUSES:
                raise ValueError(f"{key}: status must be one of {STATUSES}")
            if e["status"] == "approved" and not e.get("reviewed_by"):
                raise ValueError(f"{key}: approved entries need reviewed_by")
