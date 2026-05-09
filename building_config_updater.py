import os
import re

import yaml


def _extract_site_code(filename: str) -> str | None:
    """Extract site code (e.g. US-MTV-1667) from a UDMI YAML filename."""
    match = re.match(r"^(US-[A-Z]+-[A-Z0-9]+)_", filename)
    return match.group(1) if match else None


def _find_building_entity(building_config: dict) -> tuple[str, dict] | None:
    """Return (guid_key, entity_dict) for the FACILITIES/BUILDING entity, or None."""
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("type") == "FACILITIES/BUILDING":
            return key, value
    return None


def _find_meter_entity_by_code(meter_code: str, building_config: dict) -> tuple[str, dict] | None:
    """Return (guid_key, entity_dict) for the entity with matching code, or None."""
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("code") == meter_code:
            return key, value
    return None


def _process_meter(
    meter_guid: str,
    meter_data: dict,
    site_code: str,
    building_config: dict,
    output_dir: str,
    results: dict,
) -> None:
    """Compare one meter against a building config and write an _add or _update file."""
    meter_code = meter_data.get("code", "")
    if not meter_code:
        print("  No 'code' field in meter data, skipping.")
        results["failed"].append(meter_guid)
        return

    building_entity = _find_building_entity(building_config)
    if building_entity is None:
        print("  No FACILITIES/BUILDING entity found in building config, skipping.")
        results["failed"].append(meter_code)
        return

    building_guid, building_data = building_entity
    bc_meter = _find_meter_entity_by_code(meter_code, building_config)

    if bc_meter is not None:
        # --- UPDATE: meter exists in building config ---
        bc_meter_guid, bc_meter_data = bc_meter

        UDMI_FIELDS = {"translation", "type", "update_mask"}
        meter_entry: dict = {"operation": "UPDATE"}
        for k, v in bc_meter_data.items():
            if k not in UDMI_FIELDS:
                meter_entry[k] = v
        for field in ("translation", "type", "update_mask"):
            if field in meter_data:
                meter_entry[field] = meter_data[field]

        output = {
            "CONFIG_METADATA": {"operation": "UPDATE"},
            building_guid: {
                "code": building_data.get("code", site_code),
                "etag": building_data.get("etag", ""),
                "type": "FACILITIES/BUILDING",
            },
            bc_meter_guid: meter_entry,
        }

        out_filename = f"{site_code}_{meter_code}_update.yaml"
        out_path = os.path.join(output_dir, out_filename)
        try:
            parts = [
                yaml.dump({k: v}, sort_keys=False, default_flow_style=False)
                for k, v in output.items()
            ]
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(parts))
            print(f"  Update written: {out_path}")
            print(f"  Note: Update the site model GUID ({bc_meter_guid})")
            results["updated"].append((out_filename, bc_meter_guid))
        except Exception as e:
            print(f"  Failed to write update file: {e}")
            results["failed"].append(meter_code)

    else:
        # --- ADD: meter not yet in building config ---
        meter_entry = {"operation": "ADD"}
        meter_entry.update(meter_data)

        output = {
            "CONFIG_METADATA": {"operation": "UPDATE"},
            building_guid: {
                "code": building_data.get("code", site_code),
                "etag": building_data.get("etag", ""),
                "type": "FACILITIES/BUILDING",
            },
            meter_guid: meter_entry,
        }

        out_filename = f"{site_code}_{meter_code}_add.yaml"
        out_path = os.path.join(output_dir, out_filename)
        try:
            parts = [
                yaml.dump({k: v}, sort_keys=False, default_flow_style=False)
                for k, v in output.items()
            ]
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(parts))
            print(f"  Add written: {out_path}")
            results["added"].append(out_filename)
        except Exception as e:
            print(f"  Failed to write add file: {e}")
            results["failed"].append(meter_code)


def _print_summary(results: dict) -> None:
    print(f"\n=== Building Config Updater Summary ===")
    print(f"  Added:    {len(results['added'])}")
    for name in results["added"]:
        print(f"    {name}")
    print(f"  Updated:  {len(results['updated'])}")
    for name, guid in results["updated"]:
        print(f"    {name}  (Note: Update the site model GUID {guid})")
    if results["failed"]:
        print(f"  Failed:   {len(results['failed'])}")
        for name in results["failed"]:
            print(f"    {name}")


def run_building_config_updater_from_data(
    meter_entries: list[dict],
    building_configs_dir: str,
    output_dir: str,
) -> None:
    """Process in-memory meter entries against building configs, writing _add/_update files.

    Each entry in meter_entries must have keys: "guid", "data", "site_code".
    """
    os.makedirs(output_dir, exist_ok=True)

    # Pre-load building configs for each unique site code
    loaded_configs: dict[str, dict | None] = {}
    for entry in meter_entries:
        site_code = entry["site_code"]
        if site_code not in loaded_configs:
            config_path = os.path.join(building_configs_dir, f"{site_code}_full_building_config.yaml")
            if not os.path.isfile(config_path):
                print(f"  No building config found for site {site_code}: {config_path}")
                loaded_configs[site_code] = None
            else:
                try:
                    with open(config_path, "r", encoding="utf-8") as fh:
                        loaded_configs[site_code] = yaml.safe_load(fh)
                except Exception as e:
                    print(f"  Failed to load building config for {site_code}: {e}")
                    loaded_configs[site_code] = None

    results: dict = {"added": [], "updated": [], "failed": []}

    for entry in meter_entries:
        site_code = entry["site_code"]
        building_config = loaded_configs.get(site_code)
        if building_config is None or not isinstance(building_config, dict):
            results["failed"].append(entry.get("data", {}).get("code", entry["guid"]))
            continue
        print(f"\n--- {entry.get('data', {}).get('code', entry['guid'])} ({site_code}) ---")
        _process_meter(entry["guid"], entry["data"], site_code, building_config, output_dir, results)

    _print_summary(results)


def run_building_config_updater(input_dir: str | None = None) -> None:
    """Option 6: generate ADD/UPDATE YAMLs comparing UDMI files against building configs."""
    if input_dir is not None:
        if not os.path.isdir(input_dir):
            print(f"Provided directory not found: '{input_dir}'")
            return
    else:
        while True:
            raw = input(
                "Enter the directory containing UDMI YAML files and full_building_configs/ folder: "
            ).strip().strip('"').strip("'")
            if not raw:
                print("No input provided.")
                return
            if os.path.isdir(raw):
                input_dir = raw
                break
            print(f"Directory not found: '{raw}'")

    building_configs_dir = os.path.join(input_dir, "full_building_configs")
    if not os.path.isdir(building_configs_dir):
        print(f"full_building_configs/ subfolder not found in: {input_dir}")
        print("Run option 5 first to export building configs.")
        return

    udmi_files = sorted([
        f for f in os.listdir(input_dir)
        if f.endswith("_udmi.yaml") and os.path.isfile(os.path.join(input_dir, f))
    ])

    if not udmi_files:
        print("No *_udmi.yaml files found in the directory.")
        return

    print(f"\nFound {len(udmi_files)} UDMI YAML file(s).")

    output_dir = os.path.join(input_dir, "building_config_updates")
    os.makedirs(output_dir, exist_ok=True)

    results: dict = {"added": [], "updated": [], "failed": []}

    for filename in udmi_files:
        udmi_path = os.path.join(input_dir, filename)
        print(f"\n--- {filename} ---")

        site_code = _extract_site_code(filename)
        if not site_code:
            print("  Could not extract site code from filename, skipping.")
            results["failed"].append(filename)
            continue

        building_config_path = os.path.join(
            building_configs_dir, f"{site_code}_full_building_config.yaml"
        )
        if not os.path.isfile(building_config_path):
            print(f"  No building config found for site {site_code} at: {building_config_path}")
            results["failed"].append(filename)
            continue

        try:
            with open(building_config_path, "r", encoding="utf-8") as fh:
                building_config = yaml.safe_load(fh)
        except Exception as e:
            print(f"  Failed to load building config: {e}")
            results["failed"].append(filename)
            continue

        if not isinstance(building_config, dict):
            print("  Building config is not a valid YAML mapping, skipping.")
            results["failed"].append(filename)
            continue

        try:
            with open(udmi_path, "r", encoding="utf-8") as fh:
                udmi_data = yaml.safe_load(fh)
        except Exception as e:
            print(f"  Failed to load UDMI YAML: {e}")
            results["failed"].append(filename)
            continue

        if not isinstance(udmi_data, dict) or len(udmi_data) != 1:
            print("  Unexpected UDMI YAML structure (expected single top-level key), skipping.")
            results["failed"].append(filename)
            continue

        meter_guid = next(iter(udmi_data))
        meter_data = udmi_data[meter_guid]

        _process_meter(meter_guid, meter_data, site_code, building_config, output_dir, results)

    _print_summary(results)
