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


def run_building_config_updater() -> None:
    """Option 6: generate ADD update YAMLs for meters not yet in their building config."""
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

    results = {"added": [], "updated": [], "failed": []}

    for filename in udmi_files:
        udmi_path = os.path.join(input_dir, filename)
        print(f"\n--- {filename} ---")

        # Extract site code from filename
        site_code = _extract_site_code(filename)
        if not site_code:
            print(f"  Could not extract site code from filename, skipping.")
            results["failed"].append(filename)
            continue

        # Locate matching building config
        building_config_path = os.path.join(
            building_configs_dir, f"{site_code}_full_building_config.yaml"
        )
        if not os.path.isfile(building_config_path):
            print(f"  No building config found for site {site_code} at: {building_config_path}")
            results["failed"].append(filename)
            continue

        # Load building config
        try:
            with open(building_config_path, "r", encoding="utf-8") as fh:
                building_config = yaml.safe_load(fh)
        except Exception as e:
            print(f"  Failed to load building config: {e}")
            results["failed"].append(filename)
            continue

        if not isinstance(building_config, dict):
            print(f"  Building config is not a valid YAML mapping, skipping.")
            results["failed"].append(filename)
            continue

        # Load UDMI YAML
        try:
            with open(udmi_path, "r", encoding="utf-8") as fh:
                udmi_data = yaml.safe_load(fh)
        except Exception as e:
            print(f"  Failed to load UDMI YAML: {e}")
            results["failed"].append(filename)
            continue

        if not isinstance(udmi_data, dict) or len(udmi_data) != 1:
            print(f"  Unexpected UDMI YAML structure (expected single top-level key), skipping.")
            results["failed"].append(filename)
            continue

        meter_guid = next(iter(udmi_data))
        meter_data = udmi_data[meter_guid]
        meter_code = meter_data.get("code", "")

        if not meter_code:
            print(f"  No 'code' field found in UDMI YAML, skipping.")
            results["failed"].append(filename)
            continue

        # Check if meter already exists in building config by code
        bc_meter = _find_meter_entity_by_code(meter_code, building_config)

        # Find FACILITIES/BUILDING entity (needed for both ADD and UPDATE)
        building_entity = _find_building_entity(building_config)
        if building_entity is None:
            print(f"  No FACILITIES/BUILDING entity found in building config, skipping.")
            results["failed"].append(filename)
            continue

        building_guid, building_data = building_entity

        if bc_meter is not None:
            # --- UPDATE: meter exists in building config ---
            bc_meter_guid, bc_meter_data = bc_meter

            # Keep all BC fields except translation/type/update_mask; add UDMI versions
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
                results["failed"].append(filename)

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
                results["failed"].append(filename)

    # Summary
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
