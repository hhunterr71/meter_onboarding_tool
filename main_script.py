import json
import pandas as pd
import pyperclip # type: ignore
import yaml
import os
from translation_builder import translation_builder # type: ignore

def load_field_mapping(meter_type: str, yaml_file="standard_field_map.yaml") -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, yaml_file)
    with open(file_path, "r") as f:
        all_mappings = yaml.safe_load(f)
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

def load_unit_mapping(yaml_file="raw_units.yaml") -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, yaml_file)
    with open(file_path, "r") as f:
        canonical_to_raw = yaml.safe_load(f)
    return {
        raw_unit: canonical_unit
        for canonical_unit, raw_units in canonical_to_raw.items()
        for raw_unit in raw_units
    }

def get_meter_type():
    return input("Enter a meter type (e.g., EM, WM, GM): ").strip().upper()

def get_json_string():
    while True:
        json_str = input("Please enter the discovery json string: ").strip()
        if json_str:
            break
        print("Input cannot be empty. Please try again.")
    print()
    return json_str

    #Just here for debugging purposes.
    # return '''{"type":"bitbox_power-meter","protocol":"power-meter","id":"PV_Meter","device":"power-meter-PV_Meter","name":"PV_Meter","timestamp":"2025-03-29T07:30:59.307220Z","data":{"kW_C":{"units":"kilowatts","present-value":0.01},"kW":{"units":"kilowatts","present-value":-0.02},"Volts_BC":{"units":"volts","present-value":480.36},"Volts_AB":{"units":"volts","present-value":484.83},"Volts_CA":{"units":"volts","present-value":486.73},"Current_B":{"units":"amperes","present-value":3.14},"Current_C":{"units":"amperes","present-value":2.92},"Frequency":{"units":"hertz","present-value":60.0},"kWh_rec":{"units":"kilowatt-hours","present-value":39422.0},"Volts_C":{"units":"volts","present-value":279.02},"kWh":{"units":"kilowatt-hours","present-value":128071.0},"Volts_A":{"units":"volts","present-value":282.43},"kW_B":{"units":"kilowatts","present-value":0.01},"Current_A":{"units":"amperes","present-value":3.14},"Volts_B":{"units":"volts","present-value":276.87},"kW_A":{"units":"kilowatts","present-value":-0.03}},"version":1}'''

def prepare_dataframe(parsed, field_map, unit_map):
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

def print_and_copy_table(df):
    output_table = df[["assetName", "object_name", "standardFieldName", "raw_units", "DBO_standard_units"]]
    print("\n🔍 Mapping Review Table:")
    print(output_table.to_string(index=False))
    output_table.to_clipboard(index=False)
    print("\nTable copied to clipboard.")

def confirm_mapping():
    user_input = input("Are all relevant fields matched? (y/n): ").strip().lower()
    if user_input != "y":
        print("Restart the mapping process or update your mapping dictionaries.")
        exit()
    print()

def get_standard_fields(df):
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

def get_general_type():
    # while True:
    #     generalType = input("Please enter the generalType: ").strip()
    #     if generalType:
    #         break
    #     print("Input cannot be empty. Please try again.")
    # return generalType

    generalType = "METER"
    print(f"Please enter the generalType: {generalType}")
    return generalType

def get_type_name():
    while True:
        typeName = input("Please enter the canonical typeName: ").strip()
        if typeName:
            return typeName
        print("Input cannot be empty. Please try again.")

def add_missing_fields(df, asset_name, generalType, typeName):
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

def confirm_generate_translation():
    while True:
        confirm = input("Would you like to generate the translation? (y/n): ").strip().lower()
        if confirm in ['yes', 'y']:
            return True
        elif confirm in ['no', 'n']:
            print("❌ Translation generation cancelled.")
            exit()
        else:
            print("⚠️ Please enter 'yes' or 'no'.")

def main():
    meter_type = get_meter_type()
    try:
        field_map = load_field_mapping(meter_type)
    except ValueError as e:
        print(e)
        exit(1)

    unit_map = load_unit_mapping()

    json_str = get_json_string()
    parsed = json.loads(json_str)

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
