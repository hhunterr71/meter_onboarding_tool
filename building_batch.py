import json
import os
import shutil
import uuid
from typing import Dict, Any, List, Optional

import yaml

import pandas as pd

from field_map_utils import _load_field_map_yaml, load_field_dbo_units, load_field_standard_units
from site_model_editor import (
    load_site_model,
    validate_site_model,
    build_case_insensitive_field_map,
    process_points,
    print_review,
    apply_resolution,
    extract_asset_name_from_refs,
    build_yaml_asset_name,
    add_missing_points,
    build_translation_dataframe,
)
from field_map_utils import resolve_unmatched
from export_building_config import export_building_config
from type_matcher import run_type_matcher, get_type_name, get_type_fields
from translation_builder_udmi import build_udmi_dict


METER_PREFIXES = ("EM-", "GM-", "WM-", "PVI-", "EMV-")
WORKING_FOLDER_NAME = "meter_onboarding"

_PREFIX_TO_METER_TYPE: Dict[str, str] = {
    "EM": "EM",
    "EMV": "EM",
    "PVI": "EM",
    "WM": "WM",
    "GM": "GM",
}


def _infer_meter_type(folder_name: str) -> Optional[str]:
    prefix = folder_name.split("-")[0].upper()
    return _PREFIX_TO_METER_TYPE.get(prefix)

_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".site_models_dir")


def find_site_models(site_models_dir: str) -> List[str]:
    """Return sorted list of subfolder names that contain udmi/devices/."""
    if not os.path.isdir(site_models_dir):
        return []
    return sorted([
        name for name in os.listdir(site_models_dir)
        if os.path.isdir(os.path.join(site_models_dir, name, "udmi", "devices"))
    ])


def load_site_models_dir() -> Optional[str]:
    """Return the saved site_models directory from .site_models_dir, or None."""
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            path = f.read().strip()
        return path if path else None
    except Exception:
        return None


def save_site_models_dir(path: str) -> None:
    """Write the site_models directory path to .site_models_dir."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(path)
    except Exception:
        pass


def _load_discovery_lookup(work_dir: str) -> Dict[str, int]:
    """Return {device_id: device_num_id} from device_discovery.json, or {} on error.

    When multiple rows share the same device_id, the row with the most recent
    last_event_time is used. Null timestamps (None or the string "null") rank lowest.
    """
    path = os.path.join(work_dir, "device_discovery.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        headers = data[0]
        id_idx = headers.index("device_id")
        num_id_idx = headers.index("device_num_id")
        time_idx = headers.index("last_event_time")

        best: Dict[str, tuple] = {}  # device_id -> (row, normalized_time_str)
        for row in data[1:]:
            if len(row) <= num_id_idx or row[num_id_idx] is None:
                continue
            device_id = row[id_idx]
            t = row[time_idx] if len(row) > time_idx else None
            if t is None or t == "null":
                t = ""
            if device_id not in best or t > best[device_id][1]:
                best[device_id] = (row, t)

        return {did: int(entry[0][num_id_idx]) for did, entry in best.items()}
    except Exception:
        return {}


def _load_building_config(work_dir: str) -> Dict[str, Any]:
    """Load building config from work_dir. Prefers *_local.yaml variant over exported file."""
    try:
        files = os.listdir(work_dir)
        # Pass 1: prefer _local variant (for offline/debug use)
        for f in files:
            if f.endswith("_full_building_config_local.yaml"):
                with open(os.path.join(work_dir, f), encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    print(f"  Using local building config: {f}")
                    return data
        # Pass 2: regular exported file
        for f in files:
            if f.endswith("_full_building_config.yaml"):
                with open(os.path.join(work_dir, f), encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _prompt_site_model_selection(saved_dir: str, site_models: List[str]) -> Optional[str]:
    """Display numbered site model list and return the chosen building folder path."""
    print("\nAvailable site models:")
    for i, name in enumerate(site_models, 1):
        print(f"  {i}. {name}")
    raw = input(
        "\nEnter number to select, paste a new directory path, or Enter to cancel: "
    ).strip().strip('"').strip("'")
    if not raw:
        return None
    # If it looks like a number, pick from list
    try:
        idx = int(raw)
        if 1 <= idx <= len(site_models):
            return os.path.join(saved_dir, site_models[idx - 1])
        print(f"Invalid number. Enter 1–{len(site_models)}.")
        return None
    except ValueError:
        pass
    # Otherwise treat as a new path
    return _resolve_building_dir(raw)


def _resolve_building_dir(user_input: str) -> Optional[str]:
    """
    Determine building directory from user input.
    - If <input>/udmi/devices/ exists → single building folder, return it.
    - Otherwise → treat as site_models dir, save it, show list, prompt selection.
    """
    path = user_input.strip().strip('"').strip("'")
    if not path:
        return None

    # Single building folder?
    if os.path.isdir(os.path.join(path, "udmi", "devices")):
        return path

    # Try as a site_models directory
    if not os.path.isdir(path):
        print(f"Path not found: '{path}'")
        return None

    site_models = find_site_models(path)
    if not site_models:
        print(f"No valid site models found in: '{path}'")
        print("Expected subfolders containing udmi/devices/")
        return None

    save_site_models_dir(path)
    print(f"Saved site_models directory: {path}")
    return _prompt_site_model_selection(path, site_models)


def create_working_folders(site_models_dir: str, building_name: str) -> str:
    """Create (or reset) the meter_onboarding/<building_name> working folder."""
    parent = os.path.dirname(os.path.normpath(site_models_dir))
    work_dir = os.path.join(parent, WORKING_FOLDER_NAME, building_name)

    if os.path.isdir(work_dir):
        print(f"\nWorking folder already exists: {work_dir}")
        while True:
            choice = input(
                "  1 - Start new: delete everything and start fresh\n"
                "  2 - Work in:   keep discovery data and add/update YAMLs\n"
                "Enter choice (1 or 2): "
            ).strip()
            if choice == "1":
                shutil.rmtree(work_dir)
                os.makedirs(os.path.join(work_dir, "building_config_updates"))
                print("Working folder reset.")
                break
            elif choice == "2":
                os.makedirs(os.path.join(work_dir, "building_config_updates"), exist_ok=True)
                print("Working in existing folder.")
                break
            else:
                print("Enter 1 or 2.")
    else:
        os.makedirs(os.path.join(work_dir, "building_config_updates"))
        print(f"\nWorking folder created: {work_dir}")

    return work_dir


def _extract_building_code(devices_dir: str) -> Optional[str]:
    """Read site code from the first available device metadata.json."""
    try:
        for folder in sorted(os.listdir(devices_dir)):
            meta_path = os.path.join(devices_dir, folder, "metadata.json")
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                code = meta.get("system", {}).get("location", {}).get("site")
                if code:
                    return code
    except Exception:
        pass
    return None


_DISCOVERY_HEADERS = ["device_registry_id", "device_id", "device_num_id", "last_event_time"]


def _validate_discovery_json(path: str) -> tuple[bool, str]:
    """Return (valid, error_message). Valid if parseable JSON array-of-arrays with correct headers."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Could not read file: {e}"

    if not isinstance(data, list) or len(data) < 2:
        return False, "Expected a JSON array with at least 2 rows (header + data)."

    headers = data[0]
    if not isinstance(headers, list):
        return False, "First row must be an array of column headers."

    missing = [h for h in _DISCOVERY_HEADERS if h not in headers]
    if missing:
        return False, f"Missing required headers: {missing}"

    return True, ""


def _prompt_discovery_json(work_dir: str) -> None:
    """Ensure device_discovery.json exists and is valid; prompt user to fill it if not."""
    dest = os.path.join(work_dir, "device_discovery.json")

    # Already valid — nothing to do
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        valid, err = _validate_discovery_json(dest)
        if valid:
            print(f"Discovery file ready: {dest}")
            return
        print(f"\nDiscovery file exists but has an issue: {err}")

    # Create empty file if missing so user can open it from Explorer
    if not os.path.isfile(dest):
        with open(dest, "w", encoding="utf-8") as f:
            f.write("")
        print(f"\nDevice discovery file created (empty):\n  {dest}")

    print("Paste your device discovery JSON data into that file and save it.")
    print(f"Expected headers: {_DISCOVERY_HEADERS}")

    while True:
        input("Press Enter to check...")
        if not (os.path.isfile(dest) and os.path.getsize(dest) > 0):
            print("File is still empty. Add the JSON data and save, then press Enter.")
            continue
        valid, err = _validate_discovery_json(dest)
        if valid:
            print("Discovery data validated. Continuing.")
            break
        print(f"Validation failed: {err}")
        print("Fix the file and press Enter to try again.")


def find_device_folders(devices_dir: str) -> List[str]:
    if not os.path.isdir(devices_dir):
        raise FileNotFoundError(f"Devices directory not found: {devices_dir}")
    return sorted([
        name for name in os.listdir(devices_dir)
        if os.path.isdir(os.path.join(devices_dir, name))
        and any(name.startswith(p) for p in METER_PREFIXES)
    ])


def _preview_device_name(devices_dir: str, folder: str) -> str:
    """Return the pre-parsed DBO asset name for display, or an error indicator."""
    try:
        meter_type = _infer_meter_type(folder)
        if not meter_type:
            return "(unknown meter type)"
        meta_path = os.path.join(devices_dir, folder, "metadata.json")
        parsed = load_site_model(meta_path)
        points = parsed.get("pointset", {}).get("points") or {}
        if not points:
            return "(no points)"
        raw_name = extract_asset_name_from_refs(points, meter_type)
        if not raw_name:
            return "(name unknown)"
        return build_yaml_asset_name(raw_name, meter_type)
    except Exception:
        return "(name unknown)"


def _get_num_id_status(devices_dir: str, folder: str, discovery: Dict[str, int]) -> str:
    """Return a bracketed discovery status string, or '' if discovery is empty."""
    if not discovery:
        return ""
    if folder not in discovery:
        return "[not in discovery]"
    disc_num = discovery[folder]
    try:
        meta_path = os.path.join(devices_dir, folder, "metadata.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta_num = meta.get("cloud", {}).get("num_id")
        if meta_num is None:
            return f"[ADD {disc_num} to SM]"
        if int(meta_num) != disc_num:
            return f"[MISMATCH SM={meta_num} BC={disc_num}]"
        return f"[OK {disc_num}]"
    except Exception:
        return "[?]"


def _get_guid_status(
    devices_dir: str,
    folder: str,
    dbo_name: str,
    discovery: Dict[str, int],
    building_config: Dict[str, Any],
) -> str:
    """Return a bracketed GUID status string, or '' if preconditions aren't met."""
    if not discovery or folder not in discovery or not building_config or not dbo_name:
        return ""
    bc_guid = None
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("code") == dbo_name:
            bc_guid = key
            break
    try:
        meta_path = os.path.join(devices_dir, folder, "metadata.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta_guid = (
            meta.get("system", {}).get("physical_tag", {}).get("asset", {}).get("guid")
        )
    except Exception:
        return "[?]"
    if bc_guid is None:
        return "[NEW GUID no BC entry]"
    meta_guid_bare = meta_guid.replace("uuid://", "") if meta_guid else None
    if meta_guid_bare == bc_guid:
        return "[GUID OK]"
    return "[GUID BC\u2192SM]"


def _get_points_status(devices_dir: str, folder: str) -> str:
    """Return [GOOD], [FAIL], or '' based on whether all point names are DBO standard fields."""
    meter_type = _infer_meter_type(folder)
    if not meter_type:
        return ""
    try:
        meta_path = os.path.join(devices_dir, folder, "metadata.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        points = meta.get("pointset", {}).get("points") or {}
        if not points:
            return ""
        field_standard_units = load_field_standard_units(meter_type)
        non_dbo = [k for k in points if k not in field_standard_units]
        if not non_dbo:
            return "[GOOD]"
        return "[FAIL]"
    except Exception:
        return "[?]"


def _get_export_status(num_status: str, guid_status: str, points_status: str) -> str:
    """Return [ADD], [UPDATE], [BLOCKED], or '' based on readiness for export."""
    if points_status != "[GOOD]":
        return "[BLOCKED]" if points_status else ""
    if not num_status:
        return ""
    if not num_status.startswith("[OK "):
        return "[BLOCKED]"
    if guid_status == "[GUID OK]":
        return "[UPDATE]"
    if guid_status == "[NEW GUID no BC entry]":
        return "[ADD]"
    return "[BLOCKED]"


def _apply_guid_from_building_config(
    file_path: str, folder: str, dbo_name: str, parsed: Dict[str, Any], building_config: Dict[str, Any]
) -> None:
    """Reconcile system.physical_tag.asset.guid in metadata.json against building config."""
    bc_guid = None
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("code") == dbo_name:
            bc_guid = key
            break

    meta_guid = (
        parsed.get("system", {})
              .get("physical_tag", {})
              .get("asset", {})
              .get("guid")
    )
    meta_guid_bare = meta_guid.replace("uuid://", "") if meta_guid else None

    def _write_parsed() -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)

    def _set_guid(g: str) -> None:
        parsed.setdefault("system", {}).setdefault("physical_tag", {}).setdefault("asset", {})["guid"] = g

    if bc_guid is not None:
        if meta_guid_bare == bc_guid:
            print(f"  GUID OK: {meta_guid}")
        else:
            guid_to_write = f"uuid://{bc_guid}"
            _set_guid(guid_to_write)
            try:
                _write_parsed()
                action = "updated" if meta_guid else "added"
                print(f"  GUID {action} from building config: {guid_to_write}")
                if meta_guid:
                    print(f"    (was: {meta_guid})")
            except Exception as e:
                print(f"  Could not write GUID: {e}")
    else:
        if meta_guid:
            print(f"  Not in building config \u2014 keeping existing GUID: {meta_guid}")
        else:
            new_guid = f"uuid://{uuid.uuid4()}"
            _set_guid(new_guid)
            try:
                _write_parsed()
                print(f"  Not in building config \u2014 generated new GUID: {new_guid}")
            except Exception as e:
                print(f"  Could not write new GUID: {e}")


def select_devices(
    folders: List[str],
    devices_dir: str,
    discovery: Optional[Dict[str, int]] = None,
    building_config: Optional[Dict[str, Any]] = None,
    points_statuses: Optional[List[str]] = None,
    export_statuses: Optional[List[str]] = None,
) -> List[str]:
    labels = [_preview_device_name(devices_dir, f) for f in folders]
    num_statuses = [_get_num_id_status(devices_dir, f, discovery or {}) for f in folders]
    guid_statuses = [
        _get_guid_status(
            devices_dir, f,
            label if not label.startswith("(") else "",
            discovery or {},
            building_config or {},
        )
        for f, label in zip(folders, labels)
    ]

    has_num = any(num_statuses)
    has_guid = any(guid_statuses)
    has_pts = points_statuses is not None and any(points_statuses)
    has_export = export_statuses is not None and any(export_statuses)

    H_PROXY = "proxy_id"
    H_NAME = "meter_name"
    H_CID = "cloud_id_status"
    H_GUID = "guid_status"
    H_PTS = "points_status"
    H_EXPORT = "export_status"

    idx_w = len(str(len(folders))) + 1  # width for "N."
    col_proxy = max(len(H_PROXY), max(len(f) for f in folders))
    col_name = max(len(H_NAME), max(len(l) for l in labels))
    col_cid = max(len(H_CID), max((len(s) for s in num_statuses), default=0)) if has_num else 0
    col_guid = max(len(H_GUID), max((len(s) for s in guid_statuses), default=0)) if has_guid else 0
    col_pts = max(len(H_PTS), max((len(s) for s in points_statuses), default=0)) if has_pts else 0
    col_export = max(len(H_EXPORT), max((len(s) for s in export_statuses), default=0)) if has_export else 0

    def _row(idx: str, proxy: str, name: str, cid: str, guid: str, pts: str = "", exp: str = "") -> str:
        line = f"  {idx:<{idx_w}} {proxy:<{col_proxy}}  {name:<{col_name}}"
        if has_num:
            line += f"  {cid:<{col_cid}}"
        if has_guid:
            line += f"  {guid:<{col_guid}}"
        if has_pts:
            line += f"  {pts:<{col_pts}}"
        if has_export:
            line += f"  {exp:<{col_export}}"
        return line

    print("\nAvailable devices:")
    print(_row("#", H_PROXY, H_NAME, H_CID, H_GUID, H_PTS, H_EXPORT))
    print(_row(
        "-" * idx_w, "-" * col_proxy, "-" * col_name,
        "-" * col_cid, "-" * col_guid, "-" * col_pts, "-" * col_export,
    ))
    for i, (folder, label, ns, gs, ps, es) in enumerate(
        zip(
            folders, labels, num_statuses, guid_statuses,
            points_statuses or [""] * len(folders),
            export_statuses or [""] * len(folders),
        ), 1
    ):
        print(_row(f"{i}.", folder, label, ns, gs, ps, es))

    while True:
        raw = input("\nEnter numbers to process (e.g. 1,3) or 'all': ").strip().lower()
        if raw == "all":
            return list(folders)
        try:
            indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
            if indices and all(1 <= i <= len(folders) for i in indices):
                return [folders[i - 1] for i in indices]
        except ValueError:
            pass
        print(f"Invalid input. Enter numbers between 1 and {len(folders)}, or 'all'.")


def overwrite_json(file_path: str, parsed: Dict[str, Any], updated_points: Dict[str, Any]) -> None:
    parsed["pointset"]["points"] = updated_points
    json_string = json.dumps(parsed, indent=2)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json_string)
        print(f"Overwritten: {file_path}")
    except PermissionError:
        print(f"Permission denied: Cannot write to {file_path}")
    except Exception as e:
        print(f"Failed to overwrite file: {e}")


def run_building_batch() -> None:
    # 1. Get building directory via site_models selection or direct path
    building_dir: Optional[str] = None
    discovery: Dict[str, int] = {}
    building_config: Dict[str, Any] = {}

    saved_dir = load_site_models_dir()
    if saved_dir and os.path.isdir(saved_dir):
        site_models = find_site_models(saved_dir)
        if site_models:
            print(f"\nSite Models Directory: {saved_dir}")
            building_dir = _prompt_site_model_selection(saved_dir, site_models)

    while not building_dir:
        raw = input(
            "\nEnter site_models directory or single building folder path (or Enter to cancel): "
        ).strip().strip('"').strip("'")
        if not raw:
            return
        building_dir = _resolve_building_dir(raw)

    devices_dir = os.path.join(building_dir, "udmi", "devices")

    # Auto-create meter_onboarding structure when building came from a site_models dir
    site_models_dir = load_site_models_dir()
    if site_models_dir and (
        os.path.normpath(os.path.dirname(building_dir)) == os.path.normpath(site_models_dir)
    ):
        building_name = os.path.basename(os.path.normpath(building_dir))
        work_dir = create_working_folders(site_models_dir, building_name)

        # Pull fresh building config into working folder
        building_code = _extract_building_code(devices_dir)
        if building_code:
            local_files = [
                f for f in os.listdir(work_dir)
                if f.endswith("_full_building_config_local.yaml")
            ]
            if local_files:
                print(f"Using local building config (skipping export): {local_files[0]}")
            else:
                outfile = os.path.join(work_dir, f"{building_code}_full_building_config.yaml")
                try:
                    export_building_config(building_code, outfile)
                except Exception as e:
                    print(f"Could not pull building config: {e}")
        else:
            print("Could not determine building code from metadata — skipping config pull.")

        # Ensure discovery JSON is populated
        _prompt_discovery_json(work_dir)
        discovery = _load_discovery_lookup(work_dir)
        building_config = _load_building_config(work_dir)

    # Validate field map YAML before doing any work
    try:
        _load_field_map_yaml()
    except (FileNotFoundError, ValueError, IOError) as e:
        print(f"\nField map YAML error — please fix before running:\n  {e}")
        return

    # 2. List and select devices
    try:
        folders = find_device_folders(devices_dir)
    except FileNotFoundError as e:
        print(e)
        return

    # Filter to known meter types only (e.g. exclude VAV-, AHU-)
    folders = [f for f in folders if _infer_meter_type(f)]

    if not folders:
        print("No device folders found.")
        return

    selected = select_devices(folders, devices_dir, discovery, building_config)

    # Process each device end-to-end before moving to the next
    for folder in selected:
        file_path = os.path.join(devices_dir, folder, "metadata.json")
        print(f"\n--- Processing: {folder} ---")

        if not os.path.isfile(file_path):
            print(f"metadata.json not found in {folder}, skipping.")
            continue

        try:
            parsed = load_site_model(file_path)
        except Exception as e:
            print(f"Error reading {file_path}: {e}, skipping.")
            continue

        if not validate_site_model(parsed):
            print(f"Skipping {folder}.")
            continue

        # Apply cloud.num_id from discovery — write immediately so it persists even if skipped
        if discovery and folder in discovery:
            disc_num = discovery[folder]
            cloud = parsed.setdefault("cloud", {})
            meta_num = cloud.get("num_id")
            if meta_num is None:
                cloud["num_id"] = disc_num
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, indent=2)
                    print(f"  Added cloud.num_id = {disc_num}")
                except Exception as e:
                    print(f"  Could not write cloud.num_id: {e}")
            elif int(meta_num) != disc_num:
                print(
                    f"  WARNING: cloud.num_id mismatch — "
                    f"metadata={meta_num}, discovery={disc_num}. Not auto-corrected."
                )

        # Reconcile GUID from building config (only for devices confirmed in discovery)
        if discovery and folder in discovery and building_config:
            meter_type_hint = _infer_meter_type(folder)
            points_hint = parsed.get("pointset", {}).get("points") or {}
            raw_name_hint = extract_asset_name_from_refs(points_hint, meter_type_hint) if meter_type_hint else None
            dbo_name = build_yaml_asset_name(raw_name_hint, meter_type_hint) if raw_name_hint else ""
            _apply_guid_from_building_config(file_path, folder, dbo_name, parsed, building_config)

        while True:
            skip_prompt = input("Skip or process this meter? (Enter=Process, 2=Skip): ").strip()
            if skip_prompt in ("", "2"):
                break
            print("Invalid input. Press Enter to process or 2 to skip.")
        if skip_prompt == "2":
            continue

        meter_type = _infer_meter_type(folder)
        if not meter_type:
            meter_type_map = {"1": "EM", "2": "WM", "3": "GM"}
            while True:
                mt_prompt = input("Enter meter type (1=EM, 2=WM, 3=GM): ").strip()
                if mt_prompt in meter_type_map:
                    meter_type = meter_type_map[mt_prompt]
                    break
                print("Invalid input. Enter 1, 2, or 3.")
        try:
            ci_field_map = build_case_insensitive_field_map(meter_type)
            field_dbo_units = load_field_dbo_units(meter_type)
        except ValueError as e:
            print(e)
            print(f"Skipping {folder}.")
            continue

        points = parsed["pointset"]["points"]
        yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings", "standard_field_map.yaml")
        all_to_skip: set = set()
        all_ignored: set = set()

        while True:
            ci_field_map = build_case_insensitive_field_map(meter_type)
            updated_points, mapped_summary, unmatched, ignored = process_points(points, ci_field_map, field_dbo_units)
            all_ignored |= set(ignored)
            remaining = [k for k in unmatched if k not in all_to_skip]
            print_review(mapped_summary, remaining, ignored)

            if not remaining:
                break

            to_skip_new, retry = resolve_unmatched(remaining, meter_type, yaml_path)
            all_to_skip |= to_skip_new
            if not retry:
                break

        updated_points = apply_resolution(updated_points, all_to_skip)

        confirm = input("\nContinue with these mappings? (Enter=Yes, 2=Skip): ").strip()
        if confirm == "2":
            print("Skipping.")
            continue

        overwrite_json(file_path, parsed, updated_points)


def _write_export_yaml(
    export_st: str,
    guid: str,
    meter_data: Dict[str, Any],
    dbo_name: str,
    site_code: str,
    building_config: Dict[str, Any],
    output_dir: str,
    results: Dict[str, List[str]],
) -> None:
    """Write a _add.yaml or _update.yaml building config file for a single meter."""
    # Find building entity (for code and etag)
    building_guid: Optional[str] = None
    building_data: Dict[str, Any] = {}
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("type") == "FACILITIES/BUILDING":
            building_guid, building_data = key, value
            break

    # Find existing BC entry for this meter (needed for UPDATE)
    bc_meter_guid: Optional[str] = None
    bc_meter_data: Dict[str, Any] = {}
    for key, value in building_config.items():
        if key == "CONFIG_METADATA":
            continue
        if isinstance(value, dict) and value.get("code") == dbo_name:
            bc_meter_guid, bc_meter_data = key, value
            break

    building_entry: Dict[str, Any] = {
        "code": building_data.get("code", site_code),
        "etag": building_data.get("etag", ""),
        "type": "FACILITIES/BUILDING",
    }

    if export_st == "[ADD]":
        meter_entry: Dict[str, Any] = {"operation": "ADD"}
        meter_entry.update(meter_data)
        meter_entry.pop("update_mask", None)
        out_key = guid
        filename = f"{site_code}_{dbo_name}_add.yaml"
    else:  # UPDATE
        UDMI_FIELDS = {"translation", "type", "update_mask"}
        meter_entry = {"operation": "UPDATE"}
        for k, v in bc_meter_data.items():
            if k not in UDMI_FIELDS:
                meter_entry[k] = v
        for field in ("translation", "type", "update_mask"):
            if field in meter_data:
                meter_entry[field] = meter_data[field]
        out_key = bc_meter_guid or guid
        filename = f"{site_code}_{dbo_name}_update.yaml"

    output: Dict[str, Any] = {
        "CONFIG_METADATA": {"operation": "UPDATE"},
        building_guid: building_entry,
        out_key: meter_entry,
    }
    out_path = os.path.join(output_dir, filename)
    parts = [
        yaml.dump({k: v}, sort_keys=False, default_flow_style=False)
        for k, v in output.items()
    ]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    print(f"  Written: {out_path}")
    results["added" if export_st == "[ADD]" else "updated"].append(filename)


def run_export_batch() -> None:
    """Option 5 — Export batch: generate _add.yaml / _update.yaml building config files."""
    building_dir: Optional[str] = None
    discovery: Dict[str, int] = {}
    building_config: Dict[str, Any] = {}

    saved_dir = load_site_models_dir()
    if saved_dir and os.path.isdir(saved_dir):
        site_models = find_site_models(saved_dir)
        if site_models:
            print(f"\nSite Models Directory: {saved_dir}")
            building_dir = _prompt_site_model_selection(saved_dir, site_models)

    while not building_dir:
        raw = input(
            "\nEnter site_models directory or single building folder path (or Enter to cancel): "
        ).strip().strip('"').strip("'")
        if not raw:
            return
        building_dir = _resolve_building_dir(raw)

    devices_dir = os.path.join(building_dir, "udmi", "devices")

    site_models_dir = load_site_models_dir()
    if site_models_dir and (
        os.path.normpath(os.path.dirname(building_dir)) == os.path.normpath(site_models_dir)
    ):
        building_name = os.path.basename(os.path.normpath(building_dir))
        work_dir = create_working_folders(site_models_dir, building_name)

        building_code = _extract_building_code(devices_dir)
        if building_code:
            local_files = [
                f for f in os.listdir(work_dir)
                if f.endswith("_full_building_config_local.yaml")
            ]
            if local_files:
                print(f"Using local building config (skipping export): {local_files[0]}")
            else:
                outfile = os.path.join(work_dir, f"{building_code}_full_building_config.yaml")
                try:
                    export_building_config(building_code, outfile)
                except Exception as e:
                    print(f"Could not pull building config: {e}")
        else:
            print("Could not determine building code from metadata — skipping config pull.")

        _prompt_discovery_json(work_dir)
        discovery = _load_discovery_lookup(work_dir)
        building_config = _load_building_config(work_dir)
    else:
        print("Building dir is not inside a saved site_models directory — no work_dir created.")
        return

    output_dir = os.path.join(work_dir, "building_config_updates")
    os.makedirs(output_dir, exist_ok=True)

    # List and select devices (meter types only)
    try:
        raw_folders = find_device_folders(devices_dir)
    except FileNotFoundError as e:
        print(e)
        return

    folders = [f for f in raw_folders if _infer_meter_type(f)]

    if not folders:
        print("No device folders found.")
        return

    # Compute all statuses for the device list
    labels = [_preview_device_name(devices_dir, f) for f in folders]
    num_statuses = [_get_num_id_status(devices_dir, f, discovery) for f in folders]
    guid_statuses = [
        _get_guid_status(
            devices_dir, f,
            label if not label.startswith("(") else "",
            discovery, building_config,
        )
        for f, label in zip(folders, labels)
    ]
    points_statuses = [_get_points_status(devices_dir, f) for f in folders]
    export_statuses = [
        _get_export_status(ns, gs, ps)
        for ns, gs, ps in zip(num_statuses, guid_statuses, points_statuses)
    ]

    selected = select_devices(
        folders, devices_dir, discovery, building_config,
        points_statuses=points_statuses, export_statuses=export_statuses,
    )

    results: Dict[str, List[str]] = {"added": [], "updated": []}

    for folder in selected:
        file_path = os.path.join(devices_dir, folder, "metadata.json")
        print(f"\n--- Processing: {folder} ---")

        if not os.path.isfile(file_path):
            print(f"  metadata.json not found in {folder}, skipping.")
            continue

        try:
            parsed = load_site_model(file_path)
        except Exception as e:
            print(f"  Error reading {file_path}: {e}, skipping.")
            continue

        if not validate_site_model(parsed):
            print(f"  Skipping {folder}.")
            continue

        meter_type = _infer_meter_type(folder)
        points_hint = parsed.get("pointset", {}).get("points") or {}
        raw_name = extract_asset_name_from_refs(points_hint, meter_type) if meter_type else None
        dbo_name = build_yaml_asset_name(raw_name, meter_type) if raw_name else ""

        num_st = _get_num_id_status(devices_dir, folder, discovery)
        guid_st = _get_guid_status(devices_dir, folder, dbo_name, discovery, building_config)
        pts_st = _get_points_status(devices_dir, folder)
        export_st = _get_export_status(num_st, guid_st, pts_st)

        if export_st == "[BLOCKED]":
            print(f"  Skipping {folder} — not ready (num_id: {num_st}, guid: {guid_st}, points: {pts_st})")
            continue
        if export_st == "":
            print(f"  Skipping {folder} — no discovery data.")
            continue

        skip_prompt = input("Skip or export this meter? (Enter=Export, 2=Skip): ").strip()
        if skip_prompt == "2":
            continue

        # Cloud identifiers
        num_id = str(parsed.get("cloud", {}).get("num_id", ""))
        meta_guid = (
            parsed.get("system", {}).get("physical_tag", {}).get("asset", {}).get("guid")
        )
        if export_st == "[ADD]" and not meta_guid:
            print("  No GUID in metadata — run Option 4 first. Skipping.")
            continue
        guid = meta_guid.replace("uuid://", "") if meta_guid else ""
        site_code = parsed.get("system", {}).get("location", {}).get("site", "")

        # Filter to DBO standard fields only
        field_standard_units = load_field_standard_units(meter_type)
        yaml_points = {k: v for k, v in points_hint.items() if k in field_standard_units}
        if not yaml_points:
            print("  No recognized standard field names — has Option 4 been run? Skipping.")
            continue

        # Interactive type matching
        suggested_type, pre_add_fields = run_type_matcher(set(yaml_points.keys()), meter_type)
        type_name = get_type_name(suggestion=suggested_type)

        # Warn about fields outside the selected type
        allowed_fields = get_type_fields(type_name, meter_type)
        if allowed_fields:
            unrecognized = [k for k in yaml_points if k not in allowed_fields]
            if unrecognized:
                print(f"  Warning: {len(unrecognized)} field(s) not in {type_name}: {unrecognized}")

        # Build translation DataFrame and UDMI dict
        missing_fields = add_missing_points(dbo_name, pre_add=pre_add_fields)
        df = build_translation_dataframe(yaml_points, field_standard_units, dbo_name, "METER", type_name)
        if missing_fields:
            missing_rows = pd.DataFrame([{
                "assetName": dbo_name,
                "object_name": "MISSING",
                "standardFieldName": field,
                "raw_units": "MISSING",
                "DBO_standard_units": "MISSING",
                "generalType": "METER",
                "typeName": type_name,
            } for field in missing_fields])
            df = pd.concat([df, missing_rows], ignore_index=True)

        udmi_dict = build_udmi_dict(df, num_id=num_id, guid=guid)
        guid_key = guid if guid else ""
        meter_data = udmi_dict.get(guid_key, next(iter(udmi_dict.values()), {}))

        _write_export_yaml(
            export_st, guid_key, meter_data, dbo_name, site_code,
            building_config, output_dir, results,
        )

    print(f"\nExport complete — {len(results['added'])} added, {len(results['updated'])} updated.")
    if results["added"]:
        print("  ADD files:")
        for f in results["added"]:
            print(f"    {f}")
    if results["updated"]:
        print("  UPDATE files:")
        for f in results["updated"]:
            print(f"    {f}")
