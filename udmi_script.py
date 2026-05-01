import json
import logging
import os
from typing import Dict, Any, Tuple, List, Optional

import pandas as pd

from field_map_utils import (
    load_config,
    load_field_dbo_units,
    load_field_standard_units,
    resolve_unmatched,
)
from type_matcher import run_type_matcher, get_type_name
from translation_builder_udmi import translation_builder_udmi
from site_model_editor import add_missing_points


# ---------------------------------------------------------------------------
# UDMI-specific I/O helpers
# ---------------------------------------------------------------------------

def get_json_string() -> str:
    while True:
        json_str = input("Please enter the discovery json string: ").strip()
        if json_str:
            break
        print("Input cannot be empty. Please try again.")
    print()
    return json_str


def print_and_copy_table(df: pd.DataFrame) -> None:
    output_table = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]
    print("\nMapping Review Table:")
    print(output_table.to_string(index=False))


def confirm_mapping() -> bool:
    user_input = input("\nContinue with these mappings? (Enter=Yes, 2=Skip): ").strip()
    return user_input != "2"


def confirm_generate_translation() -> bool:
    confirm = input("\nGenerate UDMI YAML for this device? (Enter=Yes, 2=Skip): ").strip()
    return confirm != "2"


# ---------------------------------------------------------------------------
# UDMI JSON validation and dataframe prep
# ---------------------------------------------------------------------------

def validate_json_structure_udmi(parsed: Dict[str, Any]) -> bool:
    for field in ("device_id", "points"):
        if field not in parsed:
            print(f"Missing required field: '{field}'")
            return False

    if not isinstance(parsed.get("points"), dict):
        print("'points' field must be a dictionary")
        return False

    if not parsed["points"]:
        print("'points' field cannot be empty")
        return False

    for key, value in parsed["points"].items():
        if not isinstance(value, dict):
            print(f"Point entry '{key}' must be a dictionary")
            return False
        if "present-value" not in value:
            print(f"Warning: Point '{key}' missing 'present-value'")
        if "units" not in value:
            print(f"Warning: Point '{key}' missing 'units'")

    return True


def prepare_dataframe_udmi(
    parsed: Dict[str, Any],
    field_dbo_units: Dict[str, str],
    field_standard_units: Dict[str, str],
) -> Tuple[pd.DataFrame, str]:
    points = parsed["points"]
    asset_name = parsed.get("device_id", "UNKNOWN")

    rows = []
    for object_name, point_data in points.items():
        # UDMI point keys are already standard field names
        standard_field = object_name if object_name in field_dbo_units else ""
        rows.append({
            "assetName": asset_name,
            "object_name": object_name,
            "standardFieldName": standard_field,
            "raw_units": field_standard_units.get(standard_field, point_data.get("units", "")),
            "DBO_standard_units": field_dbo_units.get(standard_field, ""),
        })

    df = pd.DataFrame(rows, columns=["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"])
    return df, asset_name


def resolve_unmatched_df_udmi(
    df: pd.DataFrame,
    meter_type: str,
    yaml_path: str,
    all_to_skip: set,
) -> Tuple[pd.DataFrame, bool]:
    """
    Resolve rows where standardFieldName is empty (unmatched).
    Returns updated df (skips removed) and retry flag.
    """
    unmatched_keys: List[str] = [
        k for k in df.loc[df["standardFieldName"] == "", "object_name"].tolist()
        if k not in all_to_skip
    ]
    if not unmatched_keys:
        return df, False
    to_skip_new, retry = resolve_unmatched(unmatched_keys, meter_type, yaml_path)
    all_to_skip |= to_skip_new
    df = df[~df["object_name"].isin(all_to_skip)].reset_index(drop=True)
    return df, retry


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_udmi() -> None:
    logger = logging.getLogger(__name__)
    logger.info("Starting UDMI Translation Builder")

    # 1. Meter type — numbered input with validation
    meter_type_map = {"1": "EM", "2": "WM", "3": "GM"}
    while True:
        mt_prompt = input("Enter meter type (1=EM, 2=WM, 3=GM): ").strip()
        if mt_prompt in meter_type_map:
            meter_type = meter_type_map[mt_prompt]
            break
        print("Invalid input. Enter 1, 2, or 3.")

    try:
        field_dbo_units = load_field_dbo_units(meter_type)
        field_standard_units = load_field_standard_units(meter_type)
        logger.info("Field mapping loaded successfully")
    except ValueError as e:
        print(e)
        return
    except Exception as e:
        print(f"Error loading field mapping: {e}")
        return

    # 2. Get and parse JSON
    json_str = get_json_string()
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON format: {e}")
        return

    if not validate_json_structure_udmi(parsed):
        print("JSON validation failed. Please check the structure and try again.")
        return

    num_id = str(parsed.get("device_num_id", ""))

    cfg = load_config()
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg["defaults"]["field_map_file"])
    all_to_skip: set = set()

    # 3. Field mapping review loop
    while True:
        field_dbo_units = load_field_dbo_units(meter_type)
        field_standard_units = load_field_standard_units(meter_type)
        df, asset_name = prepare_dataframe_udmi(parsed, field_dbo_units, field_standard_units)
        df = df[~df["object_name"].isin(all_to_skip)].reset_index(drop=True)
        print_and_copy_table(df)

        if not (df["standardFieldName"] == "").any():
            break

        df, retry = resolve_unmatched_df_udmi(df, meter_type, yaml_path, all_to_skip)
        if not retry:
            break

    # 4. Confirm mappings
    if not confirm_mapping():
        print("Cancelled.")
        return

    # 5. Type matching
    present_fields = set(df.loc[
        (df["standardFieldName"] != "") & (df["standardFieldName"] != "IGNORE"),
        "standardFieldName"
    ])
    suggested_type, pre_add_fields = run_type_matcher(present_fields, meter_type)

    generalType = "METER"
    typeName = get_type_name(suggestion=suggested_type)

    df["generalType"] = generalType
    df["typeName"] = typeName

    # 6. Confirm YAML generation
    if not confirm_generate_translation():
        print("Cancelled.")
        return

    # 7. Output directory
    dir_input = input("Enter output directory for YAML: ").strip().strip('"').strip("'")
    save_dir = dir_input

    # 8. GUID
    guid_input = input("Enter GUID (press Enter to skip): ").strip()
    guid = guid_input if guid_input else "PLACEHOLDER"

    # 9. Missing fields
    missing_fields = add_missing_points(asset_name, pre_add=pre_add_fields)
    if missing_fields:
        missing_rows = pd.DataFrame([{
            "assetName": asset_name,
            "object_name": "MISSING",
            "standardFieldName": field,
            "raw_units": "MISSING",
            "DBO_standard_units": "MISSING",
            "generalType": generalType,
            "typeName": typeName,
        } for field in missing_fields])
        df = pd.concat([df, missing_rows], ignore_index=True)

    df = df[df["standardFieldName"] != "IGNORE"]
    df = df.sort_values(by="standardFieldName", ascending=False).reset_index(drop=True)

    # 10. Final table review
    print_and_copy_table(df)

    # 11. Generate YAML
    building_code = parsed.get("building_code", "")
    auto_filename = f"{building_code}_{asset_name}" if building_code else asset_name

    translation_builder_udmi(df, auto_filename=auto_filename, save_dir=save_dir, num_id=num_id, guid=guid)
    print("\nYAML Build Complete\n")
