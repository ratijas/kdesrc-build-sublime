from dataclasses import dataclass
from enum import Enum, IntFlag
import json
from typing import Any, Dict

__all__ = (
    'ScopeRestriction',
    'Option',
    'OptionEncoder',
    'OptionDecoder',
    'DOC_BASE_URL',
)

DOC_BASE_URL = "https://docs.kde.org/trunk5/en/kdesrc-build/kdesrc-build/conf-options-table.html"


class ScopeRestriction(IntFlag):
    ANY = 0
    GLOBAL = 1
    MODULE_SET = 2


@dataclass
class Option:
    name: str
    anchor: str
    scope: ScopeRestriction
    notes: str


class OptionEncoder(json.JSONEncoder):
    def default(self, obj: Any):
        if isinstance(obj, Option):
            return {
                "name": obj.name,
                "anchor": obj.anchor,
                "scope": int(obj.scope),
                "notes": obj.notes,
            }

        return json.JSONEncoder.default(self, obj)


class OptionDecoder(json.JSONDecoder):
    def __init__(self) -> None:
        def object_hook(obj: Dict) -> Any:
            if all(key in obj for key in ("name", "anchor", "scope", "notes",)):
                return Option(
                    name=obj["name"],
                    anchor=obj["anchor"],
                    scope=ScopeRestriction(obj["scope"]),
                    notes=obj["notes"],
                )
            return obj
        super().__init__(object_hook=object_hook)
