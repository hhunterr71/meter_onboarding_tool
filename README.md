# Meter Onboard Tool

Converts raw discovery JSON from meters into structured UDMI YAML translation files for DBO onboarding.

---

## Project Structure

```
meter_onboard_tool/
├── main.py                       # Entry point — run this
├── udmi_script.py                # UDMI Translation Builder flow
├── site_model_editor.py          # Single JSON Site Model Editor flow
├── building_batch.py             # Batch Site Model Editor flow
├── yaml_batch_builder.py         # Batch YAML Export flow
├── translation_builder_udmi.py   # UDMI YAML output builder
├── field_map_utils.py            # Field map loading and unmatched field resolution
├── type_matcher.py               # Canonical type matching and selection
├── mappings/
│   ├── standard_field_map.yaml   # Field name mappings per meter type (EM, WM, GM)
│   ├── canodical_type_map.yaml   # Canonical type definitions (required/optional fields)
│   └── raw_units.yaml            # Unit normalization mappings
├── tests/
│   └── test_meter_onboard.py     # Unit tests
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
1. Translation Builder (UDMI)
2. Single JSON Site Model Editor (single json input)
3. Batch Site Model Editor (full site model input)
4. Batch YAML Export (already-processed site model input)
```

---

### Mode 1 — Translation Builder (UDMI)

For UDMI-format meters with standardized field names already under a `points` key.

1. Enter meter type: `EM`, `WM`, or `GM`
2. Paste the discovery JSON string
3. Review the field mapping table
4. Confirm mappings, optionally add missing fields
5. Enter a directory to save the output
6. YAML saved automatically as `{building_code}_{device_id}_udmi.yaml`

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

### Mode 2 — Single JSON Site Model Editor

Takes a site model JSON file and renames `pointset.points` keys from raw names (e.g. `kWh`, `freq`) to standard DBO field names (e.g. `energy_accumulator`, `line_frequency_sensor`). Normalizes units and exports both the updated JSON and a UDMI translation YAML.

1. Enter the path to the site model JSON file
2. Enter meter type: `EM`, `WM`, or `GM`
3. Review the field mapping table
4. Confirm mappings, optionally add missing fields
5. Enter `generalType` and `typeName`
6. Enter output directory (defaults to the same folder as the input file)
7. Both files are saved automatically:
   - `{site}_{device_name}_sitejson.json` — updated site model with renamed keys and normalized units
   - `{site}_{device_name}_udmi.yaml` — UDMI translation YAML for the recognized points

---

### Mode 3 — Batch Site Model Editor

Processes multiple devices in a UDMI building directory in sequence. For each device it edits the `metadata.json` in place and generates a UDMI YAML.

1. Enter building directory path (expects `<dir>/udmi/devices/`)
2. Select which meter devices to process
3. For each device: choose meter type, resolve field mappings, confirm, generate YAML

---

### Mode 4 — Batch YAML Export

For buildings whose `metadata.json` files have already been processed (standard field names in place). Skips JSON editing and goes straight to type matching and YAML generation.

1. Enter building directory path
2. Select devices — meter type is auto-detected from folder prefix
3. For each device: confirm type match, handle missing fields, generate UDMI YAML

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
