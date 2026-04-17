# Meter Onboard Tool

Converts raw discovery JSON from meters into structured YAML translation files for DBO onboarding.

---

## Project Structure

```
meter_onboard_tool/
├── main.py                       # Entry point — run this
├── bitbox_script.py              # BITBOX flow + shared utilities
├── mango_script.py               # MANGO flow
├── site_model_editor.py          # Site Model Meter Editor flow
├── translation_builder.py        # BITBOX YAML output builder
├── translation_builder_mango.py  # MANGO YAML output builder
├── mappings/
│   ├── standard_field_map.yaml   # Field name mappings per meter type (EM, WM, GM)
│   └── raw_units.yaml            # Unit normalization mappings
├── tests/
│   ├── test_meter_onboard.py     # Unit + integration tests
│   └── demo_test.py              # Demo script
├── config.yaml                   # Default settings and configuration
└── requirements.txt
```

---

## Setup

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Usage

Run `main.py` and select a mode:

```
=== Meter Onboard Tool ===
1. Translation Builder (BITBOX)
2. Translation Builder (MANGO)
3. Site Model Meter Editor
```

---

### Mode 1 — Translation Builder (BITBOX)

For meters exporting data under a `data` key with raw field names (e.g. `kW`, `Frequency`).

1. Enter meter type: `EM`, `WM`, or `GM`
2. Paste the discovery JSON string
3. Review the field mapping table
4. Confirm mappings, optionally add missing fields
5. Enter `generalType` and `typeName`
6. Generate YAML — optionally save to a file

**Example output:**
```yaml
PV_Meter:
  translation:
    power_sensor:
      present_value: data.kW.present-value
      units:
        key: data.kW.units
        values:
          kilowatts: kilowatts
    line_frequency_sensor: MISSING
  type: METERS/Power
  update_mask:
    - type
    - translation
```

---

### Mode 2 — Translation Builder (MANGO)

For UDMI-format meters with standardized field names already under a `points` key.

1. Paste the discovery JSON string
2. Review the field mapping table
3. Confirm mappings, optionally add missing fields
4. Enter `generalType` and `typeName`
5. Enter a directory to save the output
6. YAML saved automatically as `{building_code}_{device_id}_mango.yaml`

**Example output:**
```yaml
power-meter-MAIN_Meter:
  translation:
    power_sensor:
      present_value: points.power_sensor.present_value
      units:
        key: pointset.points.power_sensor.unit
        values:
          kilowatts: kilowatts
  type: METERS/EM_ION
  update_mask:
    - type
    - translation
```

---

### Mode 3 — Site Model Meter Editor

Takes a site model JSON file and renames `pointset.points` keys from raw names (e.g. `kWh`, `freq`) to standard DBO field names (e.g. `energy_accumulator`, `line_frequency_sensor`). Normalizes units and exports both the updated JSON and a MANGO translation YAML.

1. Enter the path to the site model JSON file
2. Enter meter type: `EM`, `WM`, or `GM`
3. Review the field mapping table — matched fields are copied to clipboard as a comma-separated list
4. Confirm mappings, optionally add missing fields
5. Enter `generalType` and `typeName`
6. Enter output directory (defaults to the same folder as the input file)
7. Both files are saved automatically:
   - `{site}_{device_name}_json.json` — updated site model with renamed keys and normalized units
   - `{site}_{device_name}_mango.yaml` — MANGO translation YAML for the recognized points
   - YAML is also copied to clipboard

**What changes in the JSON:**
- `pointset.points` keys are renamed to standard field names
- Units are normalized (e.g. `kW` → `kilowatts`, `A` → `amperes`)
- All other fields (`system`, `cloud`, `gateway`, etc.) are preserved exactly
- Points marked `IGNORE` in the field map are dropped
- Unmatched points are kept as-is

**Example output YAML:**
```yaml
Building_PowerMeter:
  translation:
    power_sensor:
      present_value: points.power_sensor.present_value
      units:
        key: pointset.points.power_sensor.unit
        values:
          kilowatts: kilowatts
    energy_accumulator:
      present_value: points.energy_accumulator.present_value
      units:
        key: pointset.points.energy_accumulator.unit
        values:
          kilowatt_hours: kilowatt_hours
  type: METERS/EM_ION
  update_mask:
    - type
    - translation
```

---

## Testing

```bash
python -m pytest tests/test_meter_onboard.py -v
```

---

## Configuration

Edit `config.yaml` to change defaults:
- `general_type` — default generalType (e.g. `METER`)
- `field_map_file` / `unit_map_file` — paths to mapping files
- Logging level and format
- Required JSON validation fields
