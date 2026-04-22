import json
import logging
import os
from typing import Dict, Any, Tuple, List
import pandas as pd

import bitbox_script as main_script
from translation_builder_mango import translation_builder_mango
from field_map_utils import resolve_unmatched
from type_matcher import run_type_matcher


def validate_json_structure_mango(parsed: Dict[str, Any]) -> bool:
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


def prepare_dataframe_mango(
    parsed: Dict[str, Any],
    field_dbo_units: Dict[str, str],
    field_standard_units: Dict[str, str],
) -> Tuple[pd.DataFrame, str]:
    points = parsed["points"]
    asset_name = parsed.get("device_id", "UNKNOWN")

    rows = []
    for object_name, point_data in points.items():
        # Mango point keys are already standard field names
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


def resolve_unmatched_df_mango(
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


def run_mango() -> None:
    logger = logging.getLogger(__name__)
    logger.info("Starting MANGO Translation Builder")

    meter_type = main_script.get_meter_type()
    try:
        field_dbo_units = main_script.load_field_dbo_units(meter_type)
        field_standard_units = main_script.load_field_standard_units(meter_type)
        logger.info("Field mapping loaded successfully")
    except ValueError as e:
        print(e)
        return
    except Exception as e:
        print(f"Error loading field mapping: {e}")
        return

    json_str = main_script.get_json_string()
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON format: {e}")
        return

    if not validate_json_structure_mango(parsed):
        print("JSON validation failed. Please check the structure and try again.")
        return

    cfg = main_script.load_config()
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg["defaults"]["field_map_file"])
    all_to_skip: set = set()

    while True:
        field_dbo_units = main_script.load_field_dbo_units(meter_type)
        field_standard_units = main_script.load_field_standard_units(meter_type)
        df, asset_name = prepare_dataframe_mango(parsed, field_dbo_units, field_standard_units)
        df = df[~df["object_name"].isin(all_to_skip)].reset_index(drop=True)
        main_script.print_and_copy_table(df)

        if not (df["standardFieldName"] == "").any():
            break

        df, retry = resolve_unmatched_df_mango(df, meter_type, yaml_path, all_to_skip)
        if not retry:
            break

    main_script.confirm_mapping()
    main_script.get_standard_fields(df)

    present_fields = set(df.loc[
        (df["standardFieldName"] != "") & (df["standardFieldName"] != "IGNORE"),
        "standardFieldName"
    ])
    suggested_type, pre_add_fields = run_type_matcher(present_fields, meter_type)

    generalType = main_script.get_general_type()
    typeName = main_script.get_type_name(suggestion=suggested_type)

    df["generalType"] = generalType
    df["typeName"] = typeName

    df = main_script.add_missing_fields(df, asset_name, generalType, typeName, pre_add=pre_add_fields)

    if main_script.confirm_generate_translation():
        building_code = parsed.get("building_code", "")
        auto_filename = f"{building_code}_{asset_name}" if building_code else asset_name

        yaml_string = translation_builder_mango(df, auto_filename=auto_filename)
        print("\nYAML Build Complete\n")        
        # print("\nYAML Output:\n")
        # print(yaml_string)
