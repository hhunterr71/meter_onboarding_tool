import json
import logging
from typing import Dict, Any, Tuple, Optional, List
import pandas as pd
import yaml
import os
from translation_builder import translation_builder
from field_map_utils import resolve_unmatched

# Global configuration
config: Optional[Dict[str, Any]] = None

def load_config(config_file: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file"""
    global config
    if config is not None:
        return config
        
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, config_file)
    
    try:
        with open(file_path, "r", encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        print(f"⚠️  Config file not found: {file_path}. Using defaults.")
        config = {
            "defaults": {"general_type": "METER", "field_map_file": "standard_field_map.yaml", "unit_map_file": "raw_units.yaml"},
            "validation": {"required_json_fields": ["type", "data", "device"]}
        }
        return config
    except Exception as e:
        print(f"⚠️  Error loading config: {e}. Using defaults.")
        config = {
            "defaults": {"general_type": "METER", "field_map_file": "standard_field_map.yaml", "unit_map_file": "raw_units.yaml"},
            "validation": {"required_json_fields": ["type", "data", "device"]}
        }
        return config

def _load_field_map_yaml(yaml_file: Optional[str] = None) -> Dict[str, Any]:
    if yaml_file is None:
        cfg = load_config()
        yaml_file = cfg["defaults"]["field_map_file"]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, yaml_file)

    try:
        with open(file_path, "r", encoding='utf-8') as f:
            all_mappings = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Field mapping file not found: {file_path}")
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

    return {
        object_name: standard_field
        for standard_field, field_data in all_mappings[meter_type].items()
        for object_name in (field_data.get("names") or [])
    }


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


def load_unit_mapping(yaml_file: Optional[str] = None) -> Dict[str, str]:
    """Return {raw_unit: canonical_unit} from the raw_units YAML (used by mango flow)."""
    if yaml_file is None:
        config = load_config()
        yaml_file = config["defaults"]["unit_map_file"]
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, yaml_file)

    try:
        with open(file_path, "r", encoding='utf-8') as f:
            canonical_to_raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Unit mapping file not found: {file_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in unit mapping file: {e}")
    except Exception as e:
        raise IOError(f"Error reading unit mapping file: {e}")

    if not canonical_to_raw or not isinstance(canonical_to_raw, dict):
        raise ValueError("Unit mapping file is empty or invalid")

    return {
        raw_unit: canonical_unit
        for canonical_unit, raw_units in canonical_to_raw.items()
        for raw_unit in raw_units
    }

def get_meter_type() -> str:
    return input("Enter a meter type (e.g., EM, WM, GM): ").strip().upper()

def get_json_string() -> str:
    while True:
        json_str = input("Please enter the discovery json string: ").strip()
        if json_str:
            break
        print("Input cannot be empty. Please try again.")
    print()
    return json_str

def prepare_dataframe(parsed: Dict[str, Any], field_map: Dict[str, str], field_dbo_units: Dict[str, str]) -> Tuple[pd.DataFrame, str]:
    data = parsed["data"]
    df = pd.DataFrame.from_dict(data, orient='index')
    df.reset_index(inplace=True)
    df.rename(columns={"index": "object_name", "units": "raw_units"}, inplace=True)
    df = df[["object_name", "raw_units"]]

    df["assetName"] = parsed.get("name", "UNKNOWN")
    asset_name = parsed.get("name", "UNKNOWN")

    df["standardFieldName"] = df["object_name"].map(field_map).fillna("")
    df["DBO_standard_units"] = df["standardFieldName"].map(field_dbo_units).fillna("")

    df = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]

    return df, asset_name


def resolve_unmatched_df(
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


def print_and_copy_table(df: pd.DataFrame) -> None:
    output_table = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]
    print("\n🔍 Mapping Review Table:")
    print(output_table.to_string(index=False))

def confirm_mapping() -> None:
    user_input = input("Are all relevant fields matched? (y/n): ").strip().lower()
    if user_input != "y":
        print("Restart the mapping process or update your mapping dictionaries.")
        exit()
    print()

def get_standard_fields(df: pd.DataFrame) -> str:
    filtered = df.loc[
        (df["standardFieldName"] != "IGNORE") & (df["standardFieldName"] != ""),
        "standardFieldName"
    ].tolist()
    standard_fields_str = ", ".join(filtered)
    print("Standard Field Names:")
    print(standard_fields_str)
    print()
    return standard_fields_str

def get_general_type() -> str:
    config = load_config()
    default_type = config["defaults"]["general_type"]
    
    user_input = input(f"Please enter the generalType (default: {default_type}): ").strip()
    if user_input:
        return user_input
    return default_type

def get_type_name() -> str:
    while True:
        typeName = input("Please enter the canonical typeName: ").strip()
        if typeName:
            return typeName
        print("Input cannot be empty. Please try again.")

def add_missing_fields(df: pd.DataFrame, asset_name: str, generalType: str, typeName: str) -> pd.DataFrame:
    user_input = input("Are there any missing fields you would like to add? (y/n): ").strip().lower()

    if user_input == "y":
        new_fields_input = input("Enter the MISSING standardFieldName(s), separated by commas: ").strip().lower()
        missing_fields = [field.strip() for field in new_fields_input.split(",") if field.strip()]
        print(f"🆕 You entered: {missing_fields}")
    else:
        print("Continuing with standard processing...")
        missing_fields = []

    new_rows = [
        {
            "assetName": asset_name,
            "object_name": "MISSING",
            "standardFieldName": field,
            "raw_units": "MISSING",
            "DBO_standard_units": "MISSING",
            "generalType": generalType,
            "typeName": typeName
        }
        for field in missing_fields
    ]

    missing_df = pd.DataFrame(new_rows)
    df = pd.concat([df, missing_df], ignore_index=True)
    df = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units", "generalType", "typeName"]]
    df = df[df["standardFieldName"] != "IGNORE"]
    df = df.sort_values(by="standardFieldName", ascending=False).reset_index(drop=True)
    print(df)
    return df

def confirm_generate_translation() -> bool:
    while True:
        confirm = input("Would you like to generate the translation? (y/n): ").strip().lower()
        if confirm in ['yes', 'y']:
            return True
        elif confirm in ['no', 'n']:
            print("❌ Translation generation cancelled.")
            exit()
        else:
            print("⚠️ Please enter 'yes' or 'no'.")

def setup_logging() -> None:
    """Setup logging configuration"""
    config = load_config()
    log_config = config.get("logging", {})
    
    level = getattr(logging, log_config.get("level", "INFO"))
    format_str = log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    logging.basicConfig(level=level, format=format_str)

def validate_json_structure(parsed: Dict[str, Any]) -> bool:
    """Validate that the JSON has required fields and structure"""
    config = load_config()
    required_fields = config.get("validation", {}).get("required_json_fields", ["type", "data", "device"])
    
    # Check required top-level fields
    for field in required_fields:
        if field not in parsed:
            print(f"❌ Missing required field: '{field}'")
            return False
    
    # Validate data structure
    if not isinstance(parsed.get("data"), dict):
        print("❌ 'data' field must be a dictionary")
        return False
    
    # Check if data contains meter readings
    data = parsed["data"]
    if not data:
        print("❌ 'data' field cannot be empty")
        return False
    
    # Validate data structure (each entry should have units and present-value)
    for key, value in data.items():
        if not isinstance(value, dict):
            print(f"❌ Data entry '{key}' must be a dictionary")
            return False
        
        if "present-value" not in value:
            print(f"⚠️  Warning: Data entry '{key}' missing 'present-value'")
        
        if "units" not in value:
            print(f"⚠️  Warning: Data entry '{key}' missing 'units'")
    
    return True

def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Meter Onboard Tool")
    
    meter_type = get_meter_type()
    logger.info(f"Processing meter type: {meter_type}")
    
    try:
        field_map = load_field_mapping(meter_type)
        field_dbo_units = load_field_dbo_units(meter_type)
        logger.info("Field mapping loaded successfully")
    except ValueError as e:
        logger.error(f"Field mapping error: {e}")
        print(e)
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error loading field mapping: {e}")
        print(f"Error: {e}")
        exit(1)

    json_str = get_json_string()
    try:
        parsed = json.loads(json_str)
        logger.info("JSON parsed successfully")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        print(f"❌ Invalid JSON format: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected JSON parsing error: {e}")
        print(f"❌ Error parsing JSON: {e}")
        return
    
    # Validate JSON structure
    if not validate_json_structure(parsed):
        logger.error("JSON validation failed")
        print("❌ JSON validation failed. Please check the structure and try again.")
        return
    logger.info("JSON validation passed")

    cfg = load_config()
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg["defaults"]["field_map_file"])
    all_to_skip: set = set()

    while True:
        field_map = load_field_mapping(meter_type)
        df, asset_name = prepare_dataframe(parsed, field_map, field_dbo_units)
        df = df[~df["object_name"].isin(all_to_skip)].reset_index(drop=True)
        print_and_copy_table(df)

        if not (df["standardFieldName"] == "").any():
            break

        df, retry = resolve_unmatched_df(df, meter_type, yaml_path, all_to_skip)
        if not retry:
            break

    confirm_mapping()

    get_standard_fields(df)

    generalType = get_general_type()
    typeName = get_type_name()

    df["generalType"] = generalType
    df["typeName"] = typeName

    df = add_missing_fields(df, asset_name, generalType, typeName)

    if confirm_generate_translation():
        building_code = parsed.get("building_code", "")
        auto_filename = f"{building_code}_{asset_name}" if building_code else asset_name
        yaml_string = translation_builder(df, auto_filename=auto_filename)
        print("\nYAML Build Complete\n")        
        # print("\nYAML Output:\n")
        # print(yaml_string)

if __name__ == "__main__":
    main()
