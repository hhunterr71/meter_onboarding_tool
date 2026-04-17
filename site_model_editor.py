import json
import os
from typing import Dict, Any, Tuple, List

import pandas as pd

import bitbox_script as main_script
from translation_builder_mango import translation_builder_mango


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
    unit_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """
    Returns:
      updated_points   - dict with renamed keys and normalized units
      mapped_summary   - list of "original -> standard" strings for review
      unmatched        - list of keys that had no match in the field map
    """
    updated = {}
    mapped_summary = []
    unmatched = []

    for raw_key, point_data in points.items():
        standard = ci_field_map.get(raw_key.lower())
        normalized = {
            **point_data,
            "units": unit_map.get(point_data.get("units", ""), point_data.get("units", "")),
        }
        if standard is None:
            unmatched.append(raw_key)
            updated[raw_key] = normalized
        elif standard == "IGNORE":
            pass  # drop the point
        else:
            updated[standard] = normalized
            mapped_summary.append(f"  {raw_key:<40} -> {standard}")

    return updated, mapped_summary, unmatched


def print_review(mapped_summary: List[str], unmatched: List[str]) -> None:
    print("\nField Mapping Results:")
    print(f"  {'Original Key':<40}    Standard Field Name")
    print("  " + "-" * 70)
    for line in mapped_summary:
        print(line)

    if unmatched:
        print(f"\nUnmatched points (kept as-is): {len(unmatched)}")
        for key in unmatched:
            print(f"  {key}")
    else:
        print("\nAll points matched successfully.")


def add_missing_points(
    updated_points: Dict[str, Any],
    asset_name: str,
) -> Dict[str, Any]:
    user_input = input("\nAre there any missing fields you would like to add? (y/n): ").strip().lower()
    if user_input != "y":
        return updated_points

    new_fields_input = input("Enter the missing standardFieldName(s), separated by commas: ").strip()
    missing_fields = [f.strip() for f in new_fields_input.split(",") if f.strip()]

    for field in missing_fields:
        updated_points[field] = {
            "units": "MISSING",
            "writable": False,
            "ref": "MISSING",
        }
        print(f"  Added: {field}")

    return updated_points


def build_translation_dataframe(
    updated_points: Dict[str, Any],
    unit_map: Dict[str, str],
    asset_name: str,
    general_type: str,
    type_name: str,
) -> pd.DataFrame:
    rows = []
    for field_name, point_data in updated_points.items():
        raw_unit = point_data.get("units", "")
        canonical_unit = unit_map.get(raw_unit, raw_unit)
        rows.append({
            "assetName": asset_name,
            "object_name": field_name,
            "standardFieldName": field_name,
            "raw_units": canonical_unit,
            "DBO_standard_units": canonical_unit,
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

    save_path = os.path.join(save_dir, f"{auto_filename}_json.json")
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


def run_site_model_editor() -> None:
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

    # 3. Get meter type
    meter_type = input("Enter meter type (EM, WM, GM): ").strip().upper()
    try:
        ci_field_map = build_case_insensitive_field_map(meter_type)
    except ValueError as e:
        print(e)
        return

    unit_map = main_script.load_unit_mapping()

    # 4. Process points
    points = parsed["pointset"]["points"]
    updated_points, mapped_summary, unmatched = process_points(points, ci_field_map, unit_map)

    # 5. Review
    print_review(mapped_summary, unmatched)

    # Print comma-separated list of matched standard field names for external use
    unmatched_set = set(unmatched)
    matched_fields = [k for k in updated_points if k not in unmatched_set]
    fields_str = ", ".join(matched_fields)
    print(f"\nMatched Standard Fields:\n{fields_str}")

    confirm = input("\nContinue with these mappings? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    # 6. Add missing fields
    asset_name = parsed.get("system", {}).get("name", "UNKNOWN")
    updated_points = add_missing_points(updated_points, asset_name)

    # 7. Type info
    general_type = main_script.get_general_type()
    type_name = main_script.get_type_name()

    # 8. Build auto-filename
    site = parsed.get("system", {}).get("location", {}).get("site", "")
    auto_filename = f"{site}_{asset_name}" if site else asset_name

    # 9. Ask for output directory once (default: same folder as input file)
    default_dir = os.path.dirname(os.path.abspath(file_path))
    dir_input = input(f"\nEnter output directory (press Enter to use input file's folder):\n  [{default_dir}]: ").strip().strip('"').strip("'")
    save_dir = dir_input if dir_input else default_dir

    # 10. Always export both files
    save_updated_json(parsed, updated_points, auto_filename, save_dir)

    df = build_translation_dataframe(updated_points, unit_map, asset_name, general_type, type_name)
    yaml_string = translation_builder_mango(df, auto_filename=auto_filename, save_dir=save_dir)
