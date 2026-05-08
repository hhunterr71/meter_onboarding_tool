import subprocess
import re
import os
import time


# ----------------------------
# Helper functions
# ----------------------------
def run_onboard_and_get_status(building_code, topology_file_path, result_file_path):
    try:
        _, city_code, building_code_part = building_code.split("-", 2)
    except ValueError:
        print("Invalid building code format. Expected: US-XXX-YYY")
        print("\a")  # Chime for failure
        return False

    city_code = city_code.lower()
    building_code_part = building_code_part.lower()

    os.makedirs(os.path.dirname(result_file_path), exist_ok=True)

    onboard_args = [
        "stubby",
        "call",
        "blade:google.cloud.digitalbuildings.v1alpha1.digitalbuildingsservice-prod",
        "google.cloud.digitalbuildings.v1alpha1.DigitalBuildingsService.OnboardBuilding",
        "--print_status_extensions",
        "--proto2",
        f"name: 'projects/digitalbuildings/countries/us/cities/{city_code}/buildings/{building_code_part}', profile:'projects/digitalbuildings/profiles/MaintenanceOps'",
        "--set_field",
        f"topology_file=readfile({topology_file_path})"
    ]
    print("Running onboarding command...")
    onboard_result = subprocess.run(onboard_args, capture_output=True, text=True)
    if onboard_result.returncode != 0:
        print("OnboardBuilding failed (return code != 0):")
        print(onboard_result.stderr.strip())
        if onboard_result.stdout:
            print("Onboard stdout:\n", onboard_result.stdout)
        print("\a")
        return False

    onboard_combined = (onboard_result.stdout or "") + "\n" + (onboard_result.stderr or "")
    match = re.search(r'name:\s*["\']([^"\']+)["\']', onboard_combined)
    if not match:
        print("Failed to extract operation name from OnboardBuilding output")
        print("\a")
        return False

    operation_name = match.group(1)

    get_op_args = [
        "stubby",
        "call",
        "blade:google.cloud.digitalbuildings.v1alpha1.digitalbuildingsservice-prod",
        "google.cloud.digitalbuildings.v1alpha1.DigitalBuildingsService.GetOperation",
        "--print_status_extensions",
        "--proto2",
        f"--outfile={result_file_path}",
        "--binary_output",
        f"name: 'projects/digitalbuildings/countries/us/cities/{city_code}/buildings/{building_code_part}', profile:'projects/digitalbuildings/profiles/MaintenanceOps', operation_name: '{operation_name}'"
    ]

    time.sleep(10)
    check_count = 1
    while True:
        print(f"Checking operation status (attempt {check_count})...")
        get_op_result = subprocess.run(get_op_args, capture_output=True, text=True)

        file_content = ""
        try:
            if os.path.exists(result_file_path):
                with open(result_file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    file_content = fh.read()
        except Exception as e:
            print(f"Warning: couldn't read {result_file_path}: {e}")

        combined_out = file_content.strip() or ((get_op_result.stdout or "") + "\n" + (get_op_result.stderr or ""))
        combined_out = combined_out.strip()

        if get_op_result.returncode != 0:
            print("Warning: GetOperation returned non-zero exit code:", get_op_result.returncode)
            if get_op_result.stderr:
                print("GetOperation stderr:\n", get_op_result.stderr.strip())

        if re.search(r"\brunning\b", combined_out, re.I):
            if check_count <= 3:
                wait_time = 10
            elif check_count <= 6:
                wait_time = 30
            else:
                wait_time = 60
            print(f"Operation still running — will retry in {wait_time} seconds")
            time.sleep(wait_time)
            check_count += 1
            continue

        if "Successfully completed onboard operation." not in combined_out:
            print("Config onboarding failed.")
            print("\a")
            return False
        else:
            print("Config onboarding succeeded.")
        return True


def analyze_results(result_files):
    success_count = 0
    fail_count = 0
    failed_files = []

    for res_file, orig_cfg, was_skipped in result_files:
        if was_skipped:
            success_count += 1
            continue
        content = ""
        try:
            with open(res_file, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except Exception as e:
            print(f"Warning: couldn't read {res_file}: {e}")

        if "Successfully completed onboard operation." in content:
            success_count += 1
        else:
            fail_count += 1
            failed_files.append(os.path.basename(orig_cfg))

    print("\n===== Onboarding Summary =====")
    print(f"  Successful: {success_count}")
    print(f"  Failed:     {fail_count}")
    if failed_files:
        print("\n  Failed files:")
        for f in failed_files:
            print(f"    - {f}")
    # Completion chime
    for _ in range(3):
        print("\a", end="", flush=True)
        time.sleep(0.5)


# ----------------------------
# Main entry point
# ----------------------------
def run_onboard_updates(input_dir: str | None = None) -> None:
    """Option 7: submit _add.yaml and _update.yaml files to the OnboardBuilding API."""
    if input_dir is None:
        while True:
            raw = input(
                "Enter the project directory containing building_config_updates/ folder: "
            ).strip().strip('"').strip("'")
            if not raw:
                print("No input provided.")
                return
            if os.path.isdir(raw):
                input_dir = raw
                break
            print(f"Directory not found: '{raw}'")

    updates_dir = os.path.join(input_dir, "building_config_updates")
    if not os.path.isdir(updates_dir):
        print(f"building_config_updates/ subfolder not found in: {input_dir}")
        print("Run option 5 first to generate update files.")
        return

    update_files = sorted([
        f for f in os.listdir(updates_dir)
        if (f.endswith("_add.yaml") or f.endswith("_update.yaml"))
        and os.path.isfile(os.path.join(updates_dir, f))
    ])

    if not update_files:
        print("No *_add.yaml or *_update.yaml files found.")
        return

    print(f"\nFound {len(update_files)} file(s) to onboard:")
    for f in update_files:
        print(f"  {f}")

    results_dir = os.path.join(updates_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    result_files = []
    for filename in update_files:
        cfg_path = os.path.join(updates_dir, filename)

        match = re.match(r"^(US-[A-Z]+-[A-Z0-9]+)_", filename)
        if not match:
            print(f"\n  Could not extract building code from '{filename}', skipping.")
            continue
        building_code = match.group(1)

        base = os.path.splitext(filename)[0]
        result_file = os.path.join(results_dir, f"{base}_result.yaml")

        if os.path.exists(result_file):
            try:
                with open(result_file, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                if "Successfully completed onboard operation." in content:
                    print(f"\n  Skipping {filename} — already successfully onboarded.")
                    result_files.append((result_file, cfg_path, True))
                    continue
            except Exception as e:
                print(f"Warning: couldn't read {result_file}: {e}")

        print(f"\n--- Processing: {filename} ({building_code}) ---")
        run_onboard_and_get_status(building_code, cfg_path, result_file)
        result_files.append((result_file, cfg_path, False))

    analyze_results(result_files)
