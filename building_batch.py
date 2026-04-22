import json
import os
from typing import Dict, Any, List

import pandas as pd

import bitbox_script as main_script
from type_matcher import run_type_matcher
from site_model_editor import (
    load_site_model,
    validate_site_model,
    build_case_insensitive_field_map,
    process_points,
    print_review,
    apply_resolution,
    build_translation_dataframe,
    add_missing_points,
    extract_asset_name_from_refs,
    build_yaml_asset_name,
)
from field_map_utils import resolve_unmatched
from translation_builder_mango import translation_builder_mango


METER_PREFIXES = ("EM-", "GM-", "WM-", "PVI-", "EMV-")


def find_device_folders(devices_dir: str) -> List[str]:
    if not os.path.isdir(devices_dir):
        raise FileNotFoundError(f"Devices directory not found: {devices_dir}")
    return sorted([
        name for name in os.listdir(devices_dir)
        if os.path.isdir(os.path.join(devices_dir, name))
        and any(name.startswith(p) for p in METER_PREFIXES)
    ])


def select_devices(folders: List[str]) -> List[str]:
    print("\nAvailable devices:")
    for i, folder in enumerate(folders, 1):
        print(f"  {i}. {folder}")
    while True:
        raw = input("\nEnter numbers to process (e.g. 1,3) or 'all': ").strip().lower()
        if raw == "all":
            return list(folders)
        try:
            indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if indices and all(1 <= i <= len(folders) for i in indices):
                return [folders[i - 1] for i in indices]
        except ValueError:
            pass
        print(f"Invalid input. Enter numbers between 1 and {len(folders)}, or 'all'.")


def overwrite_json(file_path: str, parsed: Dict[str, Any], updated_points: Dict[str, Any]) -> None:
    parsed["pointset"]["points"] = updated_points
    json_string = json.dumps(parsed, indent=2)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json_string)
        print(f"Overwritten: {file_path}")
    except PermissionError:
        print(f"Permission denied: Cannot write to {file_path}")
    except Exception as e:
        print(f"Failed to overwrite file: {e}")


def run_building_batch() -> None:
    # 1. Get building directory
    while True:
        building_dir = input("Enter building directory path: ").strip().strip('"').strip("'")
        devices_dir = os.path.join(building_dir, "udmi", "devices")
        if os.path.isdir(devices_dir):
            break
        print(f"Directory not found: '{devices_dir}'")
        print("Expected structure: <building_dir>/udmi/devices/")

    # Validate field map YAML before doing any work
    try:
        main_script._load_field_map_yaml()
    except (FileNotFoundError, ValueError, IOError) as e:
        print(f"\nField map YAML error — please fix before running:\n  {e}")
        return

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
    processed = []

    # Phase 1: JSON rename (overwrite in place, no missing fields prompt)
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

        meter_type = input("Enter meter type (EM, WM, GM): ").strip().upper()
        try:
            ci_field_map = build_case_insensitive_field_map(meter_type)
            field_dbo_units = main_script.load_field_dbo_units(meter_type)
            field_standard_units = main_script.load_field_standard_units(meter_type)
        except ValueError as e:
            print(e)
            print(f"Skipping {folder}.")
            continue

        points = parsed["pointset"]["points"]
        yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings", "standard_field_map.yaml")
        all_to_skip: set = set()
        all_ignored: set = set()

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
        matched_fields = [k for k in updated_points if k not in all_ignored]
        # print(f"\nMatched Standard Fields:\n{', '.join(matched_fields)}")

        confirm = input("\nContinue with these mappings? (y/n): ").strip().lower()
        if confirm != "y":
            print("Skipping.")
            continue

        raw_name = extract_asset_name_from_refs(points, meter_type)
        if raw_name is None:
            raw_name = parsed.get("system", {}).get("name", "UNKNOWN")
            print(f"  Could not extract asset name from refs, falling back to: {raw_name}")
        suggested = build_yaml_asset_name(raw_name, meter_type)
        sample_ref = next((p.get("ref") for p in points.values() if p.get("ref")), None)
        if sample_ref:
            print(f"Sample ref: {sample_ref}")
        override = input(f"Asset name: [{suggested}] (press Enter to accept or type a new name): ").strip()
        asset_name = override if override else suggested
        num_id = str(parsed.get("cloud", {}).get("num_id", ""))

        overwrite_json(file_path, parsed, updated_points)
        processed.append({
            "folder": folder,
            "parsed": parsed,
            "updated_points": updated_points,
            "asset_name": asset_name,
            "field_standard_units": field_standard_units,
            "num_id": num_id,
            "ignored_keys": all_ignored,
            "meter_type": meter_type,
        })

    # Phase 2: Mango YAML (optional, iterative)
    if not processed:
        print("\nNo devices were successfully processed.")
        return

    confirm_yaml = input("\nGenerate mango YAML files for processed devices? (y/n): ").strip().lower()
    if confirm_yaml != "y":
        return

    save_dir = input("Enter output directory for YAML files: ").strip().strip('"').strip("'")

    for entry in processed:
        print(f"\n--- YAML: {entry['folder']} ---")

        yaml_points = {k: v for k, v in entry["updated_points"].items() if k not in entry["ignored_keys"]}
        suggested_type, pre_add_fields = run_type_matcher(set(yaml_points.keys()), entry["meter_type"])

        general_type = main_script.get_general_type()
        type_name = main_script.get_type_name(suggestion=suggested_type)

        missing_fields = add_missing_points(entry["asset_name"], pre_add=pre_add_fields)
        df = build_translation_dataframe(
            yaml_points,
            entry["field_standard_units"],
            entry["asset_name"], general_type, type_name,
        )

        if missing_fields:
            missing_rows = pd.DataFrame([{
                "assetName": entry["asset_name"],
                "object_name": "MISSING",
                "standardFieldName": field,
                "raw_units": "MISSING",
                "DBO_standard_units": "MISSING",
                "generalType": general_type,
                "typeName": type_name,
            } for field in missing_fields])
            df = pd.concat([df, missing_rows], ignore_index=True)

        site = entry["parsed"].get("system", {}).get("location", {}).get("site", "")
        auto_filename = f"{site}_{entry['asset_name']}" if site else entry["asset_name"]
        translation_builder_mango(df, auto_filename=auto_filename, save_dir=save_dir, num_id=entry["num_id"])
