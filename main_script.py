import json
import logging
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import pyperclip
import yaml
import os
from translation_builder import translation_builder

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

def load_field_mapping(meter_type: str, yaml_file: Optional[str] = None) -> Dict[str, str]:
    if yaml_file is None:
        config = load_config()
        yaml_file = config["defaults"]["field_map_file"]
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
    
    if meter_type not in all_mappings:
        raise ValueError(
            f"Meter type '{meter_type}' not found in field map YAML. "
            f"Available types: {', '.join(all_mappings.keys())}"
        )
    
    return {
        object_name: standard_field
        for standard_field, object_names in all_mappings[meter_type].items()
        for object_name in object_names
    }

def load_unit_mapping(yaml_file: Optional[str] = None) -> Dict[str, str]:
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

def prepare_dataframe(parsed: Dict[str, Any], field_map: Dict[str, str], unit_map: Dict[str, str]) -> Tuple[pd.DataFrame, str]:
    data = parsed["data"]
    df = pd.DataFrame.from_dict(data, orient='index')
    df.reset_index(inplace=True)
    df.columns = ["object_name", "raw_units", "present_value"]
    df = df[["object_name", "raw_units"]]

    df["assetName"] = parsed.get("device", "UNKNOWN")
    asset_name = parsed.get("device", "UNKNOWN")

    df["standardFieldName"] = df["object_name"].map(field_map).fillna("")
    df["DBO_standard_units"] = df["raw_units"].map(unit_map).fillna("")

    df = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]

    return df, asset_name

def print_and_copy_table(df: pd.DataFrame) -> None:
    output_table = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]
    print("\n🔍 Mapping Review Table:")
    print(output_table.to_string(index=False))
    output_table.to_clipboard(index=False)
    print("\nTable copied to clipboard.")

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
    pd.Series([standard_fields_str]).to_clipboard(index=False, header=False)
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
    df.to_clipboard(index=False)
    print("🔍 Data copied to clipboard:\n")
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
        logger.info("Field mapping loaded successfully")
    except ValueError as e:
        logger.error(f"Field mapping error: {e}")
        print(e)
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error loading field mapping: {e}")
        print(f"Error: {e}")
        exit(1)

    unit_map = load_unit_mapping()

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

    df, asset_name = prepare_dataframe(parsed, field_map, unit_map)

    print_and_copy_table(df)

    confirm_mapping()

    get_standard_fields(df)

    generalType = get_general_type()
    typeName = get_type_name()

    df["generalType"] = generalType
    df["typeName"] = typeName

    df = add_missing_fields(df, asset_name, generalType, typeName)

    if confirm_generate_translation():
        yaml_string = translation_builder(df)
        print("\n📄 YAML Output:\n")
        print(yaml_string)
        pyperclip.copy(yaml_string)
        print("\n📋 YAML copied to clipboard.")

if __name__ == "__main__":
    main()
