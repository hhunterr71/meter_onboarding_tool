from __future__ import annotations

import os
from typing import List, Optional, Set, Tuple

import yaml


def _get_yaml_path(yaml_path: Optional[str] = None) -> str:
    if yaml_path:
        return yaml_path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "mappings", "standard_field_map.yaml")


def _get_standard_fields_for_meter(yaml_path: str, meter_type: str) -> List[str]:
    with open(yaml_path, "r", encoding="utf-8") as f:
        all_mappings = yaml.safe_load(f) or {}
    return [k for k in all_mappings.get(meter_type, {}) if k != "IGNORE"]


def resolve_unmatched(
    unmatched: List[str],
    meter_type: str,
    yaml_path: Optional[str] = None,
) -> Tuple[Set[str], bool]:
    """
    Show sorted list of unmatched fields, then prompt for bulk action:
      (a) Map all manually — edit YAML, then retry
      (s) Skip all         — exclude all from output
      (k) Keep all         — use all raw names unchanged
      (1) One-by-one       — keep or skip each field individually

    Returns:
      to_skip: set of raw keys to exclude from output
      retry:   True if user chose 'a' and caller should reload field map and re-run
    """
    if not unmatched:
        return set(), False

    resolved_yaml_path = _get_yaml_path(yaml_path)
    sorted_unmatched = sorted(unmatched)

    print(f"\n{len(unmatched)} unmatched field(s):")
    print("  " + ", ".join(sorted_unmatched))
    print()
    print("  (a) Map all manually  — edit standard_field_map.yaml, then retry")
    print("  (s) Skip all          — exclude all from output")
    print("  (k) Keep all          — use all raw names unchanged")
    print("  (1) One-by-one        — keep or skip each field individually")

    while True:
        bulk = input("Choice [a/s/k/1]: ").strip().lower()
        if bulk in ("a", "s", "k", "1"):
            break
        print("Please enter a, s, k, or 1.")

    if bulk == "s":
        print("All unmatched fields will be skipped.")
        return set(unmatched), False

    if bulk == "k":
        print("All unmatched fields kept with raw names.")
        return set(), False

    if bulk == "a":
        available = _get_standard_fields_for_meter(resolved_yaml_path, meter_type)
        print(f"\nFields to add to standard_field_map.yaml:")
        for field in sorted_unmatched:
            print(f"  - {field}")
        print(f"\nFile: {resolved_yaml_path}")
        if available:
            print(f"\nAvailable standard fields for {meter_type}:")
            for sf in available:
                print(f"  - {sf}")
        print("\nAdd each raw name to the appropriate standard field's 'names:' list.")
        input("Press Enter when done to retry... ")
        return set(), True

    # bulk == "1": one-by-one, keep or skip only
    to_skip: Set[str] = set()
    for raw_key in sorted_unmatched:
        print(f"\n  Unmatched: '{raw_key}'")
        print("    (s) Skip — exclude from output")
        print("    (k) Keep — use raw name unchanged")
        while True:
            choice = input("  Choice [s/k]: ").strip().lower()
            if choice in ("s", "k"):
                break
            print("  Please enter s or k.")
        if choice == "s":
            to_skip.add(raw_key)
            print(f"  '{raw_key}' will be skipped.")
        else:
            print(f"  '{raw_key}' kept with raw name.")

    return to_skip, False
