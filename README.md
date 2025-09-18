# Meter Translation Tool

This tool converts raw discovery JSON output from meters into structured YAML translation files. It helps map raw device data fields and units to standardized field names and formats.

---

## Project Files

- **main_script.py**: Main command-line interface script for user interaction.
- **translation_builder.py**: Contains YAML conversion logic from processed DataFrame.
- **meter_onboard.py**: Entry point script that provides a loop interface.
- **standard_field_map.yaml**: YAML file mapping object names to standard field names by meter type.
- **raw_units.yaml**: YAML file mapping raw units to canonical DBO units.
- **config.yaml**: Configuration file for default settings and customization.

---

## Usage

1. If using the quick start method, simply run:
   ```bash
   python run.py
   ```

2. For manual setup, activate the virtual environment first:
   
   **Windows:**
   ```cmd
   venv\Scripts\activate
   python meter_onboard.py
   ```
   
   **Linux/macOS:**
   ```bash
   source venv/bin/activate
   python meter_onboard.py
   ```

3. Follow prompts to:

   - Enter meter type (e.g., EM, WM, GM).
   - Paste discovery JSON string.
   - Review mapping table (copied to clipboard).
   - Confirm or add missing standard fields.
   - Enter general and canonical type names.
   - Generate YAML translation output.
   - Optionally save the YAML file to a chosen path.

4. Outputs are automatically copied to your clipboard for easy pasting.

---

## Setup

### Quick Start (Recommended)

1. Run the setup script to create a virtual environment and install dependencies:
   ```bash
   python setup.py
   ```

2. Run the tool:
   ```bash
   python run.py
   ```

### Manual Setup

#### Windows
1. Create and activate a virtual environment:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   ```

#### Linux/macOS
1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
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

## Testing

Run the test suite to verify functionality:

```bash
# Activate virtual environment first
python -m pytest test_meter_onboard.py -v

# Run with coverage
python -m pytest test_meter_onboard.py --cov=main_script --cov=translation_builder -v
```

---

## Configuration

The tool uses `config.yaml` for configuration. You can modify:

- Default general type (defaults to "METER")
- File paths for field and unit mappings
- Logging settings
- Validation requirements

---

## Notes

- Update `standard_field_map.yaml` and `raw_units.yaml` as needed to keep mappings current.
- Missing fields can be manually added during runtime prompts.
- The tool validates inputs to ensure completeness.
- Outputs are saved only if you choose to do so and you provide a valid path.
- Check logs for detailed information about processing steps.

---

Feel free to open an issue or submit a pull request if you find bugs or want to contribute!
