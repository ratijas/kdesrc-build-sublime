from dataclasses import dataclass
from enum import Enum, IntFlag
import json
from typing import Any, Dict

__all__ = (
    'RegionTypeRestriction',
    'Option',
    'OptionEncoder',
    'OptionDecoder',
    'DOC_BASE_URL',
)

DOC_BASE_URL = "https://docs.kde.org/trunk5/en/kdesrc-build/kdesrc-build/conf-options-table.html"


class RegionTypeRestriction(IntFlag):
    ANY = 0
    GLOBAL = 1
    MODULE_SET = 2


@dataclass
class Option:
    name: str
    anchor: str
    region: RegionTypeRestriction
    notes: str


class OptionEncoder(json.JSONEncoder):
    def default(self, obj: Any):
        if isinstance(obj, Option):
            return {
                "name": obj.name,
                "anchor": obj.anchor,
                "region": int(obj.region),
                "notes": obj.notes,
            }

        return json.JSONEncoder.default(self, obj)


class OptionDecoder(json.JSONDecoder):
    def __init__(self) -> None:
        def object_hook(obj: Dict) -> Any:
            if all(key in obj for key in ("name", "anchor", "region", "notes",)):
                return Option(
                    name=obj["name"],
                    anchor=obj["anchor"],
                    region=RegionTypeRestriction(obj["region"]),
                    notes=obj["notes"],
                )
            return obj
        super().__init__(object_hook=object_hook)
