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
from type_matcher import run_type_matcher, get_type_name, get_type_fields
from translation_builder_udmi import build_udmi_dict
from export_building_config import export_building_config
from building_config_updater import run_building_config_updater_from_data


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
    if not selected:
        return

    # 3. Ask for output directory upfront
    while True:
        output_dir = input("Enter output directory for generated files: ").strip().strip('"').strip("'")
        if output_dir:
            break
        print("Output directory is required.")
    os.makedirs(output_dir, exist_ok=True)

    # 4. Pre-scan selected devices to collect unique site codes
    site_codes: set[str] = set()
    for folder in selected:
        meta_path = os.path.join(devices_dir, folder, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            parsed = load_site_model(meta_path)
            site = parsed.get("system", {}).get("location", {}).get("site", "")
            if site:
                site_codes.add(site)
        except Exception:
            pass

    # 5. Export building configs before the device processing loop
    bc_dir = os.path.join(output_dir, "full_building_configs")
    os.makedirs(bc_dir, exist_ok=True)

    if site_codes:
        print(f"\nExporting building configs for {len(site_codes)} site(s)...")
        for code in sorted(site_codes):
            outfile = os.path.join(bc_dir, f"{code}_full_building_config.yaml")
            print(f"--- Exporting: {code} ---")
            try:
                export_building_config(code, outfile)
                print(f"  Saved: {outfile}")
            except RuntimeError as e:
                print(f"  Warning: failed to export config for {code}: {e}")
    else:
        print("\nWarning: no site codes found in selected device metadata. Building config export skipped.")

    # 6. Process each device — collect meter data in memory
    meter_entries: list[dict] = []
    updates_dir = os.path.join(output_dir, "building_config_updates")

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

        # Filter yaml_points to only fields defined on the selected type
        allowed_fields = get_type_fields(type_name, meter_type)
        if allowed_fields:
            excluded = [k for k in yaml_points if k not in allowed_fields]
            if excluded:
                print(f"  Excluding {len(excluded)} point(s) not in {type_name}: {', '.join(excluded)}")
            yaml_points = {k: v for k, v in yaml_points.items() if k in allowed_fields}

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

        # Build meter data dict in memory — no file written
        site = parsed.get("system", {}).get("location", {}).get("site", "")
        udmi_dict = build_udmi_dict(df, num_id=num_id, guid=guid)
        guid_key = guid if guid is not None else ""
        meter_data = udmi_dict.get(guid_key, next(iter(udmi_dict.values()), {}))

        if not site:
            print(f"  Warning: no site code in metadata for {folder}.")

        meter_entries.append({
            "guid": guid_key,
            "data": meter_data,
            "site_code": site,
        })
        print(f"  Collected: {asset_name} ({site or 'no site code'})")

    # 7. Generate ADD/UPDATE files from collected meter data
    if meter_entries:
        print(f"\nGenerating ADD/UPDATE files for {len(meter_entries)} meter(s)...")
        run_building_config_updater_from_data(meter_entries, bc_dir, updates_dir)
    else:
        print("\nNo meter data collected.")
