from typing import Dict, Any
import pandas as pd
import yaml
import os

def translation_builder(df: pd.DataFrame) -> str:
    # Build structured YAML output grouped by device
    yaml_output: Dict[str, Any] = {}

    for _, row in df.iterrows():
        device = row['assetName']
        field_key = row['standardFieldName']

        # Initialize device structure
        if device not in yaml_output:
            yaml_output[device] = {
                'translation': {},
                'type': f"METERS/{row['typeName']}",
                'update_mask': ['type', 'translation']
            }

        translations = yaml_output[device]['translation']

        if field_key not in translations:
            if row['object_name'].lower() == "missing":
                translations[field_key] = "MISSING"
            else:
                translations[field_key] = {
                    'present_value': f"data.{row['object_name']}.present-value",
                    'units': {
                        'key': f"data.{row['object_name']}.units",
                        'values': {
                            row['DBO_standard_units']: row['raw_units']
                        }
                    }
                }

    # Convert to YAML string
    yaml_string = yaml.dump(yaml_output, sort_keys=False)

    # Ask user if they'd like to save
    save_prompt = input("\nWould you like to save the YAML output to a file? (y/n): ").strip().lower()
    if save_prompt == "y":
        save_path = input("Enter the full file path (e.g., C:\\Users\\You\\Desktop\\output.yaml): ").strip()
        
        if not save_path:
            print("❌ No file path provided. Skipping save.")
            return yaml_string
            
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, "w", encoding='utf-8') as file:
                file.write(yaml_string)
            print(f"✅ YAML file saved to: {save_path}")
        except PermissionError:
            print(f"❌ Permission denied: Cannot write to {save_path}")
        except OSError as e:
            print(f"❌ Invalid file path: {e}")
        except Exception as e:
            print(f"❌ Failed to save file: {e}")
    else:
        print("Skipping file save...")

    return yaml_string
