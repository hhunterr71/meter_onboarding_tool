from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


def get_type_name(suggestion: Optional[str] = None) -> str:
    """Prompt the user for a canonical type name, defaulting to the suggestion."""
    if suggestion:
        return suggestion
    while True:
        type_name = input("Please enter the canonical typeName: ").strip()
        if type_name:
            return type_name
        print("Input cannot be empty. Please try again.")

import yaml

_TYPE_MAP_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mappings", "canodical_type_map.yaml"
)


@dataclass
class MatchResult:
    type_name: str
    total_defined: int
    total_matched: int
    required_total: int
    required_matched: int
    missing_required: List[str]
    missing_optional: List[str]
    total_present: int = 0

    @property
    def match_pct(self) -> float:
        if self.total_present == 0:
            return 0.0
        return self.total_matched / self.total_present * 100

    @property
    def required_pct(self) -> float:
        if self.required_total == 0:
            return 100.0
        return self.required_matched / self.required_total * 100


def load_type_map(yaml_path: Optional[str] = None) -> Dict:
    path = yaml_path or _TYPE_MAP_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise FileNotFoundError(f"Canonical type map not found: {path}")


def _score_one(type_name: str, present: Set[str], type_def: Dict, total_present: int) -> MatchResult:
    required = [f for f, v in type_def.items() if v == "required"]
    optional = [f for f, v in type_def.items() if v == "optional"]
    return MatchResult(
        type_name=type_name,
        total_defined=len(required) + len(optional),
        total_matched=sum(1 for f in required if f in present) + sum(1 for f in optional if f in present),
        required_total=len(required),
        required_matched=sum(1 for f in required if f in present),
        missing_required=[f for f in required if f not in present],
        missing_optional=[f for f in optional if f not in present],
        total_present=total_present,
    )


def rank_types(present: Set[str], category: str, type_map: Dict) -> List[MatchResult]:
    total_present = len(present)
    results = [
        _score_one(type_name, present, type_def, total_present)
        for type_name, type_def in (type_map.get(category) or {}).items()
        if type_def  # skip undefined (bare key) types
    ]
    results.sort(key=lambda r: (r.match_pct, r.required_pct), reverse=True)
    return results


def display_match_table(ranked: List[MatchResult]) -> None:
    if not ranked:
        print("  No defined types found for this category.")
        return
    col = 38
    print(f"\n  {'#':<4} {'Type':<{col}} {'Match%':>7}  {'Req%':>5}  Missing Required")
    print("  " + "─" * (col + 32))
    for i, r in enumerate(ranked, 1):
        missing = ", ".join(r.missing_required) if r.missing_required else "—"
        print(f"  {i:<4} {r.type_name:<{col}} {r.match_pct:>6.0f}%  {r.required_pct:>4.0f}%  {missing}")
    print()


def run_type_matcher(
    present: Set[str],
    meter_type: str,
    yaml_path: Optional[str] = None,
) -> Tuple[Optional[str], List[str]]:
    """
    Display ranked type matches and guide the user to a type selection.

    Returns:
        suggested_type_name: top-ranked type name (None if no types defined)
        pre_add_fields:      missing required fields the user agreed to add as placeholders
    """
    try:
        type_map = load_type_map(yaml_path)
    except FileNotFoundError as e:
        print(f"  Warning: {e}\n  Skipping type matching.")
        return None, []

    ranked = rank_types(present, meter_type, type_map)
    if not ranked:
        print("  No type definitions found for this category. Skipping type matching.")
        return None, []

    print("\n--- Type Match Results ---")
    display_match_table(ranked)

    # Let user pick a type by number; Enter defaults to #1
    while True:
        raw = input(f"  Select type # (press Enter for #1 — {ranked[0].type_name}): ").strip()
        if raw == "":
            selected = ranked[0]
            break
        if raw.isdigit() and 1 <= int(raw) <= len(ranked):
            selected = ranked[int(raw) - 1]
            break
        print(f"  Please enter a number between 1 and {len(ranked)}, or press Enter.")

    print(f"  Selected: {selected.type_name}")
    pre_add: List[str] = []

    if selected.required_pct == 100.0:
        print(f"  ({selected.match_pct:.0f}% overall, all required fields present)")
    else:
        print(f"  Missing required fields:")
        for f in selected.missing_required:
            print(f"    - {f}")
        while True:
            ans = input("  Add these as MISSING placeholders in the YAML? (Enter=Yes, 2=No): ").strip()
            if ans in ("", "2"):
                break
            print("  Invalid input. Press Enter for Yes or 2 for No.")
        if ans != "2":
            pre_add = selected.missing_required[:]
            print(f"  {len(pre_add)} placeholder(s) will be added.")

    print()
    return selected.type_name, pre_add
