import os
import json
import pandas as pd

METER_PREFIXES = ("EM-", "GM-", "WM-", "PVI-", "EMV-")

PREFIX_TO_METER_TYPE = {
    "EM-": "EM",
    "GM-": "GM",
    "WM-": "WM",
    "PVI-": "EM",
    "EMV-": "EM",
}


def get_meter_type(device):
    for prefix, meter_type in PREFIX_TO_METER_TYPE.items():
        if device.startswith(prefix):
            return meter_type
    return None


site_models_dir = input("Enter path to site models directory: ").strip().strip('"').strip("'")
output_xlsx = "pointset_refs.xlsx"

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

            rows.append({
                "building": building,
                "device": device,
                "meter_type": meter_type or "",
                "point": point_name,
                "ref": ref,
                "units": point_data.get("units", ""),
            })

df = pd.DataFrame(rows, columns=["building", "device", "meter_type", "point", "ref", "units"])

with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="Raw Points", index=False)

print(f"\nWrote {len(rows)} rows to {output_xlsx}")
print(f"  Sheet 'Raw Points': {len(df)} rows")
