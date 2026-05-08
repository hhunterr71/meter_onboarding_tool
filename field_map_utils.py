from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_config: Optional[Dict[str, Any]] = None


def load_config(config_file: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file (cached after first load)."""
    global _config
    if _config is not None:
        return _config
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, config_file)
    _defaults: Dict[str, Any] = {
        "defaults": {
            "general_type": "METER",
            "field_map_file": "mappings/standard_field_map.yaml",
            "unit_map_file": "raw_units.yaml",
        }
    }
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f)
        return _config
    except FileNotFoundError:
        _config = _defaults
        return _config
    except Exception:
        _config = _defaults
        return _config


# ---------------------------------------------------------------------------
# Field map loading
# ---------------------------------------------------------------------------

def _load_field_map_yaml(yaml_file: Optional[str] = None) -> Dict[str, Any]:
    if yaml_file is None:
        yaml_file = _get_yaml_path()
    else:
        if not os.path.isabs(yaml_file):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            yaml_file = os.path.join(base_dir, yaml_file)
    try:
        with open(yaml_file, "r", encoding="utf-8") as f:
            all_mappings = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Field mapping file not found: {yaml_file}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in field mapping file: {e}")
    except Exception as e:
        raise IOError(f"Error reading field mapping file: {e}")
    if not all_mappings or not isinstance(all_mappings, dict):
        raise ValueError("Field mapping file is empty or invalid")
    return all_mappings


def _validate_meter_type(all_mappings: Dict[str, Any], meter_type: str) -> None:
    if meter_type not in all_mappings:
        raise ValueError(
            f"Meter type '{meter_type}' not found in field map YAML. "
            f"Available types: {', '.join(all_mappings.keys())}"
        )


def load_field_mapping(meter_type: str, yaml_file: Optional[str] = None) -> Dict[str, str]:
    """Return {object_name: standard_field_name} for the given meter type."""
    all_mappings = _load_field_map_yaml(yaml_file)
    _validate_meter_type(all_mappings, meter_type)
    result = {
        object_name: standard_field
        for standard_field, field_data in all_mappings[meter_type].items()
        for object_name in (field_data.get("names") or [])
    }
    # Also map each standard field name to itself so already-processed points
    # still have their units corrected on a second run.
    for standard_field in all_mappings[meter_type]:
        if standard_field != "IGNORE":
            result[standard_field.lower()] = standard_field
    return result


def load_field_dbo_units(meter_type: str, yaml_file: Optional[str] = None) -> Dict[str, str]:
    """Return {standard_field_name: dbo_unit} for the given meter type."""
    all_mappings = _load_field_map_yaml(yaml_file)
    _validate_meter_type(all_mappings, meter_type)
    return {
        standard_field: field_data.get("dbo_unit", "")
        for standard_field, field_data in all_mappings[meter_type].items()
        if standard_field != "IGNORE"
    }


def load_field_standard_units(meter_type: str, yaml_file: Optional[str] = None) -> Dict[str, str]:
    """Return {standard_field_name: standard_unit} for the given meter type."""
    all_mappings = _load_field_map_yaml(yaml_file)
    _validate_meter_type(all_mappings, meter_type)
    return {
        standard_field: field_data.get("standard_unit", "")
        for standard_field, field_data in all_mappings[meter_type].items()
        if standard_field != "IGNORE"
    }


# ---------------------------------------------------------------------------
# Unmatched field resolution (existing code below)
# ---------------------------------------------------------------------------


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
