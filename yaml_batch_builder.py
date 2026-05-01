import os

import pandas as pd

from field_map_utils import load_field_standard_units
from building_batch import find_device_folders, select_devices
from site_model_editor import (
    load_site_model,
    validate_site_model,
    build_translation_dataframe,
    add_missing_points,
    build_yaml_asset_name,
)
from type_matcher import run_type_matcher, get_type_name
from translation_builder_udmi import translation_builder_udmi


def _detect_meter_type(folder_name: str) -> str:
    """Auto-detect meter type from device folder name prefix."""
    upper = folder_name.upper()
    if upper.startswith("WM-"):
        return "WM"
    if upper.startswith("GM-"):
        return "GM"
    if upper.startswith("EM-") or upper.startswith("EMV-"):
        return "EM"
    if upper.startswith("PVI-"):
        print("  Note: PVI- prefix detected — defaulting meter type to EM.")
        return "EM"
    return ""


def run_yaml_batch_builder() -> None:
    # 1. Get building directory
    while True:
        building_dir = input("Enter building directory path: ").strip().strip('"').strip("'")
        devices_dir = os.path.join(building_dir, "udmi", "devices")
        if os.path.isdir(devices_dir):
            break
        print(f"Directory not found: '{devices_dir}'")
        print("Expected structure: <building_dir>/udmi/devices/")

    # 2. List and select devices
    try:
        folders = find_device_folders(devices_dir)
    except FileNotFoundError as e:
        print(e)
        return

    if not folders:
        print("No device folders found.")
        return

    selected = select_devices(folders)
    save_dir: str = ""

    for folder in selected:
        file_path = os.path.join(devices_dir, folder, "metadata.json")
        print(f"\n--- Processing: {folder} ---")

        if not os.path.isfile(file_path):
            print(f"metadata.json not found in {folder}, skipping.")
            continue

        try:
            parsed = load_site_model(file_path)
        except Exception as e:
            print(f"Error reading {file_path}: {e}, skipping.")
            continue

        if not validate_site_model(parsed):
            print(f"Skipping {folder}.")
            continue

        while True:
            skip_prompt = input("Skip or process this meter? (Enter=Process, 2=Skip): ").strip()
            if skip_prompt in ("", "2"):
                break
            print("Invalid input. Press Enter to process or 2 to skip.")
        if skip_prompt == "2":
            continue

        # Auto-detect meter type from folder prefix
        meter_type = _detect_meter_type(folder)
        if not meter_type:
            meter_type_map = {"1": "EM", "2": "WM", "3": "GM"}
            while True:
                mt_prompt = input(
                    f"Could not detect meter type for '{folder}'. Enter type (1=EM, 2=WM, 3=GM): "
                ).strip()
                if mt_prompt in meter_type_map:
                    meter_type = meter_type_map[mt_prompt]
                    break
                print("Invalid input. Enter 1, 2, or 3.")
        else:
            print(f"  Detected meter type: {meter_type}")

        try:
            field_standard_units = load_field_standard_units(meter_type)
        except ValueError as e:
            print(e)
            print(f"Skipping {folder}.")
            continue

        points = parsed["pointset"]["points"]

        # Filter to only recognized standard field names for this meter type
        yaml_points = {k: v for k, v in points.items() if k in field_standard_units}
        if not yaml_points:
            print(
                f"  No recognized standard field names found in {folder}. "
                "Has this building been processed yet?"
            )
            continue

        # Asset name
        raw_name = parsed.get("system", {}).get("name", folder)
        suggested = build_yaml_asset_name(raw_name, meter_type)
        sample_ref = next((p.get("ref") for p in points.values() if p.get("ref")), None)
        if sample_ref:
            print(f"Sample ref: {sample_ref}")
        override = input(
            f"Asset name: [{suggested}] (press Enter to accept or type a new name): "
        ).strip()
        asset_name = override if override else suggested

        # Cloud IDs
        num_id = str(parsed.get("cloud", {}).get("num_id", ""))
        guid = (
            parsed.get("system", {})
            .get("physical_tag", {})
            .get("asset", {})
            .get("guid")
        )
        if isinstance(guid, str):
            guid = guid.replace("uuid://", "")

        # Type matching
        suggested_type, pre_add_fields = run_type_matcher(set(yaml_points.keys()), meter_type)

        general_type = "METER"
        type_name = get_type_name(suggestion=suggested_type)

        # Build DataFrame and handle missing fields
        missing_fields = add_missing_points(asset_name, pre_add=pre_add_fields)
        df = build_translation_dataframe(
            yaml_points, field_standard_units, asset_name, general_type, type_name
        )

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

        # Output directory (remembered across devices)
        if save_dir:
            dir_prompt = f"Enter output directory for YAML [{save_dir}]: "
        else:
            dir_prompt = "Enter output directory for YAML: "
        dir_input = input(dir_prompt).strip().strip('"').strip("'")
        if dir_input:
            save_dir = dir_input

        if not save_dir:
            print("No output directory provided, skipping YAML.")
            continue

        site = parsed.get("system", {}).get("location", {}).get("site", "")
        auto_filename = f"{site}_{asset_name}" if site else asset_name
        translation_builder_udmi(
            df, auto_filename=auto_filename, save_dir=save_dir, num_id=num_id, guid=guid
        )
