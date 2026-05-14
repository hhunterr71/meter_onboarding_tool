import os
import json
import csv
import yaml

METER_PREFIXES = ("EM-", "GM-", "WM-", "PVI-", "EMV-")

PREFIX_TO_METER_TYPE = {
    "EM-": "EM",
    "GM-": "GM",
    "WM-": "WM",
    "PVI-": "EM",
    "EMV-": "EM",
}

FIELD_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "mappings",
    "standard_field_map.yaml",
)


def load_yaml_map():
    with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_lookup(all_mappings, meter_type):
    """Return (name_to_standard dict, ignore_names set) for a meter type."""
    if meter_type not in all_mappings:
        return {}, set()

    name_to_standard = {}
    ignore_names = set()

    for standard_field, field_data in all_mappings[meter_type].items():
        names = field_data.get("names") or []
        if standard_field == "IGNORE":
            for n in names:
                ignore_names.add(n.lower())
        else:
            for n in names:
                name_to_standard[n.lower()] = standard_field
            # Allow already-DBO-named points to match themselves
            name_to_standard[standard_field.lower()] = standard_field

    return name_to_standard, ignore_names


def get_meter_type(device):
    for prefix, meter_type in PREFIX_TO_METER_TYPE.items():
        if device.startswith(prefix):
            return meter_type
    return None


site_models_dir = input("Enter path to site models directory: ").strip()
output_csv = "pointset_refs.csv"

all_mappings = load_yaml_map()

# Pre-build lookups for every meter type present in the YAML
lookups = {mt: build_lookup(all_mappings, mt) for mt in all_mappings}

rows = []

for building in sorted(os.listdir(site_models_dir)):
    building_path = os.path.join(site_models_dir, building)
    devices_path = os.path.join(building_path, "udmi", "devices")

    if not os.path.isdir(devices_path):
        continue

    print(f"Processing {building}...")

    for device in sorted(os.listdir(devices_path)):
        if not device.startswith(METER_PREFIXES):
            continue

        meter_type = get_meter_type(device)
        name_to_standard, ignore_names = lookups.get(meter_type, ({}, set()))

        metadata_path = os.path.join(devices_path, device, "metadata.json")
        if not os.path.isfile(metadata_path):
            continue

        with open(metadata_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  Failed to parse {metadata_path}: {e}")
                continue

        points = data.get("pointset", {}).get("points", {})
        for point_name, point_data in points.items():
            ref = point_data.get("ref")
            if not ref:
                continue

            point_lower = point_name.lower()

            if point_lower in ignore_names:
                dbo_point = ""
                flag = "IGNORE"
            elif point_lower in name_to_standard:
                dbo_point = name_to_standard[point_lower]
                flag = ""
            else:
                dbo_point = ""
                flag = "not in standard field map"

            rows.append({
                "building": building,
                "device": device,
                "point": point_name,
                "dbo_point": dbo_point,
                "ref": ref,
                "flag": flag,
            })

with open(output_csv, "w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=["building", "device", "point", "dbo_point", "ref", "flag"]
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"\nWrote {len(rows)} rows to {output_csv}")
