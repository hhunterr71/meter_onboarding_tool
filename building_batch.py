import json
import os
from typing import Dict, Any, List

from field_map_utils import _load_field_map_yaml, load_field_dbo_units
from site_model_editor import (
    load_site_model,
    validate_site_model,
    build_case_insensitive_field_map,
    process_points,
    print_review,
    apply_resolution,
)
from field_map_utils import resolve_unmatched


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
        _load_field_map_yaml()
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

    # Process each device end-to-end before moving to the next
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

        meter_type_map = {"1": "EM", "2": "WM", "3": "GM"}
        while True:
            mt_prompt = input("Enter meter type (1=EM, 2=WM, 3=GM): ").strip()
            if mt_prompt in meter_type_map:
                meter_type = meter_type_map[mt_prompt]
                break
            print("Invalid input. Enter 1, 2, or 3.")
        try:
            ci_field_map = build_case_insensitive_field_map(meter_type)
            field_dbo_units = load_field_dbo_units(meter_type)
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

        confirm = input("\nContinue with these mappings? (Enter=Yes, 2=Skip): ").strip()
        if confirm == "2":
            print("Skipping.")
            continue

        overwrite_json(file_path, parsed, updated_points)
