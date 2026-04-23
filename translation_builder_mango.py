from typing import Dict, Any
import pandas as pd
import uuid
import yaml
import os

def translation_builder_mango(df: pd.DataFrame, auto_filename: str = "output", save_dir: str | None = None, num_id: str = "") -> str:
    yaml_output: Dict[str, Any] = {}

    for _, row in df.iterrows():
        field_key = row['standardFieldName']
        if not field_key:
            continue
        device = row['assetName']

        if not yaml_output:
            yaml_output = {
                'cloud_device_id': num_id,
                'code': device,
                'translation': {},
                'type': f"METERS/{row['typeName']}",
                'update_mask': ['type', 'translation'],
            }

        translations = yaml_output['translation']

        if field_key not in translations:
            if row['object_name'].lower() == "missing":
                translations[field_key] = "MISSING"
            else:
                translations[field_key] = {
                    'present_value': f"points.{field_key}.present_value",
                    'units': {
                        'key': f"pointset.points.{field_key}.unit",
                        'values': {
                            row['DBO_standard_units']: row['raw_units']
                        }
                    }
                }

    guid = str(uuid.uuid4())
    yaml_string = yaml.dump({guid: yaml_output}, sort_keys=False)

    if save_dir is None:
        # Interactive mode (Mode 2)
        save_prompt = input("\nWould you like to save the YAML output to a file? (y/n): ").strip().lower()
        if save_prompt == "y":
            save_dir = input("Enter the directory to save to (e.g., C:\\Users\\You\\Desktop): ").strip().strip('"').strip("'")
        else:
            print("Skipping file save...")
            return yaml_string

    if not save_dir:
        print("No directory provided. Skipping save.")
        return yaml_string

    save_path = os.path.join(save_dir, f"{auto_filename}_mango.yaml")
    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(save_path, "w", encoding='utf-8') as file:
            file.write(yaml_string)
        print(f"YAML file saved to: {save_path}")
    except PermissionError:
        print(f"Permission denied: Cannot write to {save_path}")
    except OSError as e:
        print(f"Invalid directory path: {e}")
    except Exception as e:
        print(f"Failed to save file: {e}")

    return yaml_string
