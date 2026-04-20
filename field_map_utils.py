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
    For each unmatched raw key, prompt: (s)kip, (k)eep as-is, (m)ap manually.

    "m" tells the user to manually add the field to standard_field_map.yaml,
    then waits for Enter and returns retry=True so the caller can reload the
    field map and re-run processing.

    Returns:
      to_skip:  set of raw keys to exclude from output
      retry:    True if user edited YAML and caller should re-run processing
    """
    if not unmatched:
        return set(), False

    resolved_yaml_path = _get_yaml_path(yaml_path)
    to_skip: Set[str] = set()
    to_map: List[str] = []

    print(f"\n{len(unmatched)} unmatched field(s) require resolution:")

    for raw_key in unmatched:
        print(f"\n  Unmatched: '{raw_key}'")
        print("    (s) Skip     — exclude from output")
        print("    (k) Keep     — use raw name unchanged")
        print("    (m) Map      — add manually to standard_field_map.yaml")
        while True:
            choice = input("  Choice [s/k/m]: ").strip().lower()
            if choice in ("s", "k", "m"):
                break
            print("  Please enter s, k, or m.")

        if choice == "s":
            to_skip.add(raw_key)
            print(f"  '{raw_key}' will be skipped.")
        elif choice == "k":
            print(f"  '{raw_key}' kept with raw name.")
        else:
            to_map.append(raw_key)
            print(f"  '{raw_key}' marked for manual mapping.")

    if to_map:
        available = _get_standard_fields_for_meter(resolved_yaml_path, meter_type)
        print(f"\nFields to add to standard_field_map.yaml:")
        for field in to_map:
            print(f"  - {field}")
        print(f"\nFile: {resolved_yaml_path}")
        if available:
            print(f"\nAvailable standard fields for {meter_type}:")
            for sf in available:
                print(f"  - {sf}")
        print("\nAdd each raw name to the appropriate standard field's 'names:' list.")
        input("Press Enter when done to retry... ")
        return to_skip, True

    return to_skip, False
