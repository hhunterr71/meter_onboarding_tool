# Meter Translation Tool

This tool converts raw discovery JSON output from meters into structured YAML translation files. It helps map raw device data fields and units to standardized field names and formats.

---

## Project Files

- **main_script.py**: Main command-line interface script for user interaction.
- **meter_translation_builder.py**: Contains YAML conversion logic from processed DataFrame.
- **standard_field_map.yaml**: YAML file mapping object names to standard field names by meter type.
- **raw_units.yaml**: YAML file mapping raw units to canonical DBO units.

---

## Usage

1. Run the main script:

   ```bash
   python main_script.py
   ```

2. Follow prompts to:

   - Enter meter type (e.g., EM, WM, GM).
   - Paste discovery JSON string.
   - Review mapping table (copied to clipboard).
   - Confirm or add missing standard fields.
   - Enter general and canonical type names.
   - Generate YAML translation output.
   - Optionally save the YAML file to a chosen path.

3. Outputs are automatically copied to your clipboard for easy pasting.

---

## Dependencies

Install required Python packages with:

```bash
pip install pandas pyperclip pyyaml
```

---

## Example YAML Output

```yaml
PV_Meter:
  translation:
    kW:
      present_value: data.kW.present-value
      units:
        key: data.kW.units
        values:
          kilowatts: kilowatts
    Frequency: MISSING
  type: METERS/Power
  update_mask:
    - type
    - translation
```

---

## Notes

- Update `standard_field_map.yaml` and `raw_units.yaml` as needed to keep mappings current.
- Missing fields can be manually added during runtime prompts.
- The tool validates inputs to ensure completeness.
- Outputs are saved only if you choose to do so and you provide a valid path.

---

Feel free to open an issue or submit a pull request if you find bugs or want to contribute!
