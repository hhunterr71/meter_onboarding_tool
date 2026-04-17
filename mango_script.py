import json
import logging
from typing import Dict, Any, Tuple
import pandas as pd
import pyperclip

import bitbox_script as main_script
from translation_builder_mango import translation_builder_mango


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


def prepare_dataframe_mango(parsed: Dict[str, Any], unit_map: Dict[str, str]) -> Tuple[pd.DataFrame, str]:
    points = parsed["points"]
    asset_name = parsed.get("device_id", "UNKNOWN")

    rows = []
    for field_name, point_data in points.items():
        rows.append({
            "assetName": asset_name,
            "object_name": field_name,
            "standardFieldName": field_name,
            "raw_units": point_data.get("units", ""),
            "DBO_standard_units": unit_map.get(point_data.get("units", ""), ""),
        })

    df = pd.DataFrame(rows, columns=["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"])
    return df, asset_name


def run_mango() -> None:
    logger = logging.getLogger(__name__)
    logger.info("Starting MANGO Translation Builder")

    unit_map = main_script.load_unit_mapping()

    json_str = main_script.get_json_string()
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON format: {e}")
        return

    if not validate_json_structure_mango(parsed):
        print("JSON validation failed. Please check the structure and try again.")
        return

    df, asset_name = prepare_dataframe_mango(parsed, unit_map)

    main_script.print_and_copy_table(df)
    main_script.confirm_mapping()
    main_script.get_standard_fields(df)

    generalType = main_script.get_general_type()
    typeName = main_script.get_type_name()

    df["generalType"] = generalType
    df["typeName"] = typeName

    df = main_script.add_missing_fields(df, asset_name, generalType, typeName)

    if main_script.confirm_generate_translation():
        building_code = parsed.get("building_code", "")
        auto_filename = f"{building_code}_{asset_name}" if building_code else asset_name

        yaml_string = translation_builder_mango(df, auto_filename=auto_filename)
        print("\nYAML Output:\n")
        print(yaml_string)
        pyperclip.copy(yaml_string)
        print("\nYAML copied to clipboard.")
