import json
import os
from typing import Dict, Any, Tuple, List, Optional, Set

import pandas as pd

import bitbox_script as main_script
from translation_builder_mango import translation_builder_mango
from field_map_utils import resolve_unmatched


def load_site_model(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_site_model(parsed: Dict[str, Any]) -> bool:
    if "pointset" not in parsed or "points" not in parsed.get("pointset", {}):
        print("Missing required field: 'pointset.points'")
        return False
    if not parsed["pointset"]["points"]:
        print("'pointset.points' is empty")
        return False
    return True


def build_case_insensitive_field_map(meter_type: str) -> Dict[str, str]:
    """Load field map and return {raw_name_lower: standard_field_name}."""
    field_map = main_script.load_field_mapping(meter_type)
    return {k.lower(): v for k, v in field_map.items()}


def process_points(
    points: Dict[str, Any],
    ci_field_map: Dict[str, str],
    field_dbo_units: Dict[str, str],
) -> Tuple[Dict[str, Any], List[str], List[str], List[str]]:
    """
    Returns:
      updated_points - renamed keys + IGNORE points kept with raw key
      mapped_summary - list of "original -> standard" strings for review
      unmatched      - list of keys with no match in the field map
      ignored        - list of keys that mapped to IGNORE (kept in JSON, skipped in YAML)
    """
    updated = {}
    mapped_summary = []
    unmatched = []
    ignored = []

    for raw_key, point_data in points.items():
        standard = ci_field_map.get(raw_key.lower())
        if standard is None:
            unmatched.append(raw_key)
            updated[raw_key] = point_data  # keep as-is
        elif standard == "IGNORE":
            updated[raw_key] = point_data  # keep unchanged in JSON
            ignored.append(raw_key)        # track for YAML exclusion
        else:
            normalized = {**point_data, "units": field_dbo_units.get(standard, point_data.get("units", ""))}
            updated[standard] = normalized
            mapped_summary.append(f"  {raw_key:<40} -> {standard}")

    return updated, mapped_summary, unmatched, ignored


def apply_resolution(
    updated_points: Dict[str, Any],
    to_skip: Set[str],
) -> Dict[str, Any]:
    """Remove skipped keys from updated_points."""
    return {k: v for k, v in updated_points.items() if k not in to_skip}


def print_review(mapped_summary: List[str], unmatched: List[str], ignored: List[str] = []) -> None:
    print("\nField Mapping Results:")
    print(f"  {'Original Key':<40}    Standard Field Name")
    print("  " + "-" * 70)
    for line in mapped_summary:
        print(line)

    if ignored:
        print(f"\nIgnored points (kept in JSON, skipped in YAML): {len(ignored)}")
        for key in ignored:
            print(f"  {key}")

    if unmatched:
        print(f"\nUnmatched points (kept as-is): {len(unmatched)}")
        for key in unmatched:
            print(f"  {key}")
    else:
        print("\nAll points matched successfully.")


def add_missing_points(asset_name: str) -> List[str]:
    user_input = input("\nAre there any missing fields you would like to add? (y/n): ").strip().lower()
    if user_input != "y":
        return []

    new_fields_input = input("Enter the missing standardFieldName(s), separated by commas: ").strip()
    missing_fields = [f.strip() for f in new_fields_input.split(",") if f.strip()]
    for field in missing_fields:
        print(f"  Added: {field}")
    return missing_fields


def build_translation_dataframe(
    updated_points: Dict[str, Any],
    field_standard_units: Dict[str, str],
    asset_name: str,
    general_type: str,
    type_name: str,
) -> pd.DataFrame:
    rows = []
    for field_name, point_data in updated_points.items():
        dbo_unit = point_data.get("units", "")
        standard_unit = field_standard_units.get(field_name, dbo_unit)
        rows.append({
            "assetName": asset_name,
            "object_name": field_name,
            "standardFieldName": field_name,
            "raw_units": standard_unit,
            "DBO_standard_units": dbo_unit,
            "generalType": general_type,
            "typeName": type_name,
        })
    return pd.DataFrame(rows)


def save_updated_json(
    parsed: Dict[str, Any],
    updated_points: Dict[str, Any],
    auto_filename: str,
    save_dir: str,
) -> None:
    parsed["pointset"]["points"] = updated_points
    json_string = json.dumps(parsed, indent=2)

    save_path = os.path.join(save_dir, f"{auto_filename}_sitejson.json")
    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(json_string)
        print(f"Updated JSON saved to: {save_path}")
    except PermissionError:
        print(f"Permission denied: Cannot write to {save_path}")
    except OSError as e:
        print(f"Invalid directory path: {e}")
    except Exception as e:
        print(f"Failed to save file: {e}")


def extract_asset_name_from_refs(points: Dict[str, Any], meter_type: str) -> Optional[str]:
    """
    For each point, use the key's underscore count to determine how many trailing
    ref segments belong to the field name, strip them, then locate the meter-type
    anchor (e.g. 'EM-') to extract the asset name. Returns the most-voted candidate,
    or None if no valid candidate is found.
    """
    search_prefix = f"{meter_type}-"
    candidates: Dict[str, int] = {}

    for point_key, point_data in points.items():
        ref = point_data.get("ref", "")
        if not ref:
            continue
        num_segments = point_key.count("_") + 1
        ref_parts = ref.split("_")
        if len(ref_parts) <= num_segments:
            continue
        device_str = "_".join(ref_parts[:-num_segments])
        idx = device_str.find(search_prefix)
        if idx != -1:
            name = device_str[idx:]
            candidates[name] = candidates.get(name, 0) + 1

    if not candidates:
        return None
    return max(candidates, key=lambda k: candidates[k])


def build_yaml_asset_name(raw_name: str, meter_type: str) -> str:
    """Apply meter-type prefix: EM → power-meter-, WM/GM → utility-."""
    prefix = "power-meter" if meter_type == "EM" else "utility"
    return f"{prefix}-{raw_name}"


def run_site_model_editor() -> None:
    # --- Phase 1: Update site model JSON ---

    # 1. Get file path
    while True:
        file_path = input("Enter the path to the site model JSON file: ").strip().strip('"').strip("'")
        if os.path.isfile(file_path):
            break
        print(f"File not found: '{file_path}'")
        print("Tip: On Windows, you can right-click the file and use 'Copy as path', then paste here.")

    # 2. Load and validate
    try:
        parsed = load_site_model(file_path)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        return
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    if not validate_site_model(parsed):
        print("JSON validation failed.")
        return

    num_id = str(parsed.get("cloud", {}).get("num_id", ""))

    # 3. Get meter type and process points
    meter_type = input("Enter meter type (EM, WM, GM): ").strip().upper()
    try:
        ci_field_map = build_case_insensitive_field_map(meter_type)
        field_dbo_units = main_script.load_field_dbo_units(meter_type)
        field_standard_units = main_script.load_field_standard_units(meter_type)
    except ValueError as e:
        print(e)
        return

    points = parsed["pointset"]["points"]
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings", "standard_field_map.yaml")
    all_to_skip: Set[str] = set()
    all_ignored: Set[str] = set()

    # 4. Review and resolve unmatched (retry loop for manual YAML edits)
    while True:
        ci_field_map = build_case_insensitive_field_map(meter_type)
        updated_points, mapped_summary, unmatched, ignored = process_points(points, ci_field_map, field_dbo_units)
        all_ignored |= set(ignored)
        remaining = [k for k in unmatched if k not in all_to_skip]
        print_review(mapped_summary, remaining, ignored)

        if not remaining:
            break

        to_skip_new, retry = resolve_unmatched(remaining, meter_type, yaml_path)
        all_to_skip |= to_skip_new
        if not retry:
            break

    updated_points = apply_resolution(updated_points, all_to_skip)
    matched_fields = [k for k in updated_points]
    print(f"\nMatched Standard Fields:\n{', '.join(matched_fields)}")

    confirm = input("\nContinue with these mappings? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    # 5. Save updated JSON
    raw_name = extract_asset_name_from_refs(points, meter_type)
    if raw_name is None:
        raw_name = parsed.get("system", {}).get("name", "UNKNOWN")
        print(f"Could not extract asset name from refs, falling back to: {raw_name}")
    suggested = build_yaml_asset_name(raw_name, meter_type)
    sample_ref = next((p.get("ref") for p in points.values() if p.get("ref")), None)
    if sample_ref:
        print(f"\nSample ref: {sample_ref}")
    override = input(f"Asset name: [{suggested}] (press Enter to accept or type a new name): ").strip()
    asset_name = override if override else suggested
    site = parsed.get("system", {}).get("location", {}).get("site", "")
    auto_filename = f"{site}_{asset_name}" if site else asset_name

    default_dir = os.path.dirname(os.path.abspath(file_path))
    dir_input = input(f"\nEnter output directory (press Enter to use input file's folder):\n  [{default_dir}]: ").strip().strip('"').strip("'")
    save_dir = dir_input if dir_input else default_dir

    save_updated_json(parsed, updated_points, auto_filename, save_dir)

    # --- Phase 2: Generate mango YAML ---

    confirm_yaml = input("\nGenerate mango YAML for this device? (y/n): ").strip().lower()
    if confirm_yaml != "y":
        return

    missing_fields = add_missing_points(asset_name)
    general_type = main_script.get_general_type()
    type_name = main_script.get_type_name()

    yaml_points = {k: v for k, v in updated_points.items() if k not in all_ignored}
    df = build_translation_dataframe(yaml_points, field_standard_units, asset_name, general_type, type_name)

    if missing_fields:
        missing_rows = pd.DataFrame([{
            "assetName": asset_name,
            "object_name": "MISSING",
            "standardFieldName": field,
            "raw_units": "MISSING",
            "DBO_standard_units": "MISSING",
            "generalType": general_type,
            "typeName": type_name,
        } for field in missing_fields])
        df = pd.concat([df, missing_rows], ignore_index=True)

    translation_builder_mango(df, auto_filename=auto_filename, save_dir=save_dir, num_id=num_id)
