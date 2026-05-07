import subprocess
import re
import os
import sys
import time


def export_building_config(building_code, outfile_path):
    """Run ExportBuildingConfig, poll until result is written to outfile, then clean gibberish.

    Returns True on success. Raises RuntimeError on failure (instead of sys.exit)
    so callers can handle errors without terminating the process.
    """

    # ----------------------------
    # Parse building code
    # ----------------------------
    try:
        _, city_code, building_code_part = building_code.split("-", 2)
    except ValueError:
        raise RuntimeError(f"Invalid building code format '{building_code}'. Expected: US-XXX-YYY")

    city_code = city_code.lower()
    building_code_part = building_code_part.lower()

    # Ensure parent directory for outfile exists
    os.makedirs(os.path.dirname(os.path.abspath(outfile_path)), exist_ok=True)

    # ----------------------------
    # First command: ExportBuildingConfig
    # ----------------------------
    export_args = [
        "stubby",
        "call",
        "blade:google.cloud.digitalbuildings.v1alpha1.digitalbuildingsservice-prod",
        "google.cloud.digitalbuildings.v1alpha1.DigitalBuildingsService.ExportBuildingConfig",
        "--deadline=60000",
        "--print_status_extensions",
        "--proto2",
        f"name: 'projects/digitalbuildings/countries/us/cities/{city_code}/buildings/{building_code_part}', profile:'projects/digitalbuildings/profiles/MaintenanceOps'"
    ]

    print("Running export building config command...")
    export_result = subprocess.run(export_args, capture_output=True, text=True)

    if export_result.returncode != 0:
        msg = export_result.stderr.strip()
        raise RuntimeError(f"ExportBuildingConfig failed (return code != 0):\n{msg}")

    combined_out = (export_result.stdout or "") + "\n" + (export_result.stderr or "")

    # ----------------------------
    # Extract operation_name
    # ----------------------------
    match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", combined_out)
    if not match:
        raise RuntimeError("Failed to extract operation_name from ExportBuildingConfig output")

    operation_name = match.group(1)

    # ----------------------------
    # Second command: GetOperation
    # ----------------------------
    get_op_args = [
        "stubby",
        "call",
        "blade:google.cloud.digitalbuildings.v1alpha1.digitalbuildingsservice-prod",
        "google.cloud.digitalbuildings.v1alpha1.DigitalBuildingsService.GetOperation",
        "--print_status_extensions",
        "--proto2",
        f"--outfile={outfile_path}",
        "--binary_output",
        f"name: 'projects/digitalbuildings/countries/us/cities/{city_code}/buildings/{building_code_part}', profile:'projects/digitalbuildings/profiles/MaintenanceOps', operation_name: '{operation_name}'"
    ]

    time.sleep(10)

    for attempt in range(1, 4):  # 3 tries max
        print(f"Checking operation status (attempt {attempt})...")
        get_op_result = subprocess.run(get_op_args, capture_output=True, text=True)

        if get_op_result.returncode != 0:
            print(f"Warning: GetOperation failed with exit code {get_op_result.returncode}")
            if get_op_result.stderr:
                print("stderr:\n", get_op_result.stderr.strip())

        # Try to read the outfile and check for "running"
        if os.path.exists(outfile_path):
            try:
                with open(outfile_path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                if content.strip():
                    if "running" in content.lower():
                        print("Operation still running — retrying in 10 seconds...")
                    else:
                        clean_export_file(outfile_path)
                        return True
            except Exception as e:
                print(f"Warning: couldn't read outfile {outfile_path}: {e}")

        if attempt < 3:
            time.sleep(10)

    raise RuntimeError("Export did not complete successfully (still running after 3 attempts).")


def _collect_building_codes_from_dir(project_dir: str) -> list:
    """Scan *_udmi.yaml filenames in project_dir and return unique site codes."""
    codes = set()
    for filename in os.listdir(project_dir):
        if not filename.endswith("_udmi.yaml"):
            continue
        match = re.match(r"^(US-[A-Z]+-[A-Z0-9]+)_", filename)
        if match:
            codes.add(match.group(1))
        else:
            print(f"  Warning: could not extract site code from '{filename}', skipping.")

    if not codes:
        print("No *_udmi.yaml files with a recognizable site code found.")

    return sorted(codes)


def run_export_batch() -> None:
    """Option 5: export building configs for one or more buildings."""
    raw = input(
        "Enter a building code (US-XXX-YYY) or a path to a project directory containing UDMI YAML files: "
    ).strip().strip('"').strip("'")

    if not raw:
        print("No input provided.")
        return

    # Determine mode: directory or building code
    if os.path.isdir(raw):
        building_dir = raw
        print(f"Directory detected — scanning for building codes in {building_dir} ...")
        building_codes = _collect_building_codes_from_dir(building_dir)
        if not building_codes:
            print("No building codes found in UDMI YAML filenames.")
            return
        print(f"\nFound {len(building_codes)} unique building code(s):")
        for code in building_codes:
            print(f"  {code}")
        output_root = os.path.join(building_dir, "full_building_configs")
    else:
        building_codes = [raw]
        output_root = os.path.join(os.getcwd(), "full_building_configs")

    os.makedirs(output_root, exist_ok=True)
    print(f"\nOutputs will be saved to: {output_root}\n")

    results = {"success": [], "failed": []}

    for code in building_codes:
        outfile = os.path.join(output_root, f"{code}_full_building_config.yaml")
        print(f"--- Exporting: {code} ---")
        try:
            export_building_config(code, outfile)
            print(f"  Saved: {outfile}")
            results["success"].append(code)
        except RuntimeError as e:
            print(f"  Failed: {e}")
            results["failed"].append(code)

    # Summary
    print(f"\n=== Export Summary ===")
    print(f"  Successful: {len(results['success'])}")
    for code in results["success"]:
        print(f"    {code}")
    if results["failed"]:
        print(f"  Failed:     {len(results['failed'])}")
        for code in results["failed"]:
            print(f"    {code}")


def clean_export_file(outfile_path):
    """Remove gibberish characters before CONFIG_METADATA: in the exported file."""
    try:
        with open(outfile_path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()

        marker = "CONFIG_METADATA:"
        idx = content.find(marker)
        if idx == -1:
            print("⚠️ Warning: CONFIG_METADATA not found in file. Leaving file unchanged.")
            return

        cleaned_content = content[idx:]
        with open(outfile_path, "w", encoding="utf-8") as fh:
            fh.write(cleaned_content)

        print("✅ Building config successfully refreshed")

    except Exception as e:
        print(f"⚠️ Failed to clean file {outfile_path}: {e}")


# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    building_code = input("Enter building code (format US-XXX-YYY): ").strip()
    outfile_path = input("Enter absolute path for output full_building_config.yaml: ").strip()

    try:
        export_building_config(building_code, outfile_path)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)