import os
import json
import csv
 
METER_PREFIXES = ("EM-", "GM-", "WM-", "PVI-", "EMV-")
 
site_models_dir = input("Enter path to site models directory: ").strip()
output_csv = "pointset_refs.csv"
 
rows = []
 
for building in os.listdir(site_models_dir):
    building_path = os.path.join(site_models_dir, building)
    devices_path = os.path.join(building_path, "udmi", "devices")
 
    if not os.path.isdir(devices_path):
        continue
 
    print(f"Processing {building}...")
 
    for device in os.listdir(devices_path):
        if not device.startswith(METER_PREFIXES):
            continue
 
        device_path = os.path.join(devices_path, device)
        metadata_path = os.path.join(device_path, "metadata.json")
 
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
            if ref:
                rows.append({
                    "building": building,
                    "device": device,
                    "point": point_name,
                    "ref": ref,
                })
 
with open(output_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["building", "device", "point", "ref"])
    writer.writeheader()
    writer.writerows(rows)
 
print(f"\nWrote {len(rows)} rows to {output_csv}")