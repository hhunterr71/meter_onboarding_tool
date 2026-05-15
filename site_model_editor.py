import json
import os
import re
from typing import Dict, Any, Tuple, List, Optional, Set

import pandas as pd

from field_map_utils import load_field_mapping, load_field_dbo_units, resolve_unmatched


def load_site_model(file_path: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_site_model(parsed: Dict[str, Any]) -> bool:
    if "pointset" not in parsed or "points" not in parsed.get("pointset", {}):
        print("Missing required field: 'pointset.points'")
        return False
    if not parsed["pointset"]["points"]:
        print("'pointset.points' is empty")
        return False
    return True


def build_case_insensitive_field_map(meter_type: str) -> Dict[str, str]:
    """Load field map and return {raw_name_lower: standard_field_name}."""
    field_map = load_field_mapping(meter_type)
    return {k.lower(): v for k, v in field_map.items()}


def process_points(
    points: Dict[str, Any],
    ci_field_map: Dict[str, str],
    field_dbo_units: Dict[str, str],
) -> Tuple[Dict[str, Any], List[str], List[str], List[str]]:
    """
    Returns:
      updated_points - renamed keys + IGNORE points kept with raw key
      mapped_summary - list of "original -> standard" strings for review
      unmatched      - list of keys with no match in the field map
      ignored        - list of keys that mapped to IGNORE (kept in JSON, skipped in YAML)
    """
    updated = {}
    mapped_summary = []
    unmatched = []
    ignored = []

    for raw_key, point_data in points.items():
        standard = ci_field_map.get(raw_key.lower())
        if standard is None:
            unmatched.append(raw_key)
            updated[raw_key] = point_data  # keep as-is
        elif standard == "IGNORE":
            updated[raw_key] = point_data  # keep unchanged in JSON
            ignored.append(raw_key)        # track for YAML exclusion
        else:
            normalized = {**point_data, "units": field_dbo_units.get(standard, point_data.get("units", ""))}
            updated[standard] = normalized
            mapped_summary.append(f"  {raw_key:<40} -> {standard}")

    return updated, mapped_summary, unmatched, ignored


def apply_resolution(
    updated_points: Dict[str, Any],
    to_skip: Set[str],
) -> Dict[str, Any]:
    """Remove skipped keys from updated_points."""
    return {k: v for k, v in updated_points.items() if k not in to_skip}


def print_review(mapped_summary: List[str], unmatched: List[str], ignored: List[str] = []) -> None:
    print("\nField Mapping Results:")
    print(f"  {'Original Key':<40}    Standard Field Name")
    print("  " + "-" * 70)
    for line in mapped_summary:
        print(line)

    if ignored:
        print(f"\nIgnored points (kept in JSON, skipped in YAML): {len(ignored)}")
        for key in ignored:
            print(f"  {key}")

    if unmatched:
        print(f"\nUnmatched points (kept as-is): {len(unmatched)}")
        for key in unmatched:
            print(f"  {key}")
    else:
        print("\nAll points matched successfully.")


def add_missing_points(asset_name: str, pre_add: Optional[List[str]] = None) -> List[str]:
    all_missing: List[str] = list(pre_add) if pre_add else []

    if pre_add:
        print(f"  Pre-adding {len(pre_add)} required placeholder(s): {', '.join(pre_add)}")

    prompt = (
        "\nAre there any additional missing fields you would like to add? (Enter=No, 2=Yes): "
        if pre_add else
        "\nAre there any missing fields you would like to add? (Enter=No, 2=Yes): "
    )
    while True:
        user_input = input(prompt).strip()
        if user_input in ("", "2"):
            break
        print("Invalid input. Press Enter for No or 2 for Yes.")
    if user_input != "2":
        return all_missing

    new_fields_input = input("Enter the missing standardFieldName(s), separated by commas: ").strip()
    extra = [f.strip() for f in new_fields_input.split(",") if f.strip()]
    for field in extra:
        print(f"  Added: {field}")
    all_missing.extend(extra)
    return all_missing


def build_translation_dataframe(
    updated_points: Dict[str, Any],
    field_standard_units: Dict[str, str],
    asset_name: str,
    general_type: str,
    type_name: str,
) -> pd.DataFrame:
    rows = []
    for field_name, point_data in updated_points.items():
        dbo_unit = point_data.get("units", "")
        standard_unit = field_standard_units.get(field_name, dbo_unit)
        rows.append({
            "assetName": asset_name,
            "object_name": field_name,
            "standardFieldName": field_name,
            "raw_units": standard_unit,
            "DBO_standard_units": dbo_unit,
            "generalType": general_type,
            "typeName": type_name,
        })
    return pd.DataFrame(rows)


def save_updated_json(
    parsed: Dict[str, Any],
    updated_points: Dict[str, Any],
    auto_filename: str,
    save_dir: str,
) -> None:
    parsed["pointset"]["points"] = updated_points
    json_string = json.dumps(parsed, indent=2)

    save_path = os.path.join(save_dir, f"{auto_filename}_sitejson.json")
    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(json_string)
        print(f"Updated JSON saved to: {save_path}")
    except PermissionError:
        print(f"Permission denied: Cannot write to {save_path}")
    except OSError as e:
        print(f"Invalid directory path: {e}")
    except Exception as e:
        print(f"Failed to save file: {e}")


def _strip_and_deduplicate(device_str: str) -> Optional[str]:
    """
    Strip BACnet network prefix from device_str, then deduplicate if the device
    name was embedded twice (Accuvim / PV-Inverter style).

    Strips up to two leading underscore-segments:
      1. Network type code: 2-5 uppercase letters  (e.g. DP, UC, IP)
      2. Channel identifier (optional): uppercase-start word ending in digits (e.g. Comm2, Ch1)

    Then strips an optional Modbus device-address block (keeps type-instance as part of name):
      3. Literal "dev" keyword
      4. Numeric device address (e.g. 100)

    The type-instance tag (e.g. EM-1, WM-2) is intentionally kept — it disambiguates
    multiple meters on the same bus and is meaningful in the BC device code.

    Then collapses repeated halves:
      DP_Comm2_MAIN_Meter                                        -> MAIN_Meter
      DP_Comm0_dev_100_EM-1_Main-L1-PGE  (CampusTotal_Volts_AN stripped as suffix)
                                                                 -> EM-1_Main-L1-PGE
      DP_Accuvim_Meter_Site_Accuvim_Meter_Site                   -> Accuvim_Meter_Site  (doubled)
      DP_PV_Inverter-01_PV_Inverter-01                           -> PV_Inverter-01  (doubled, hyphens)
    """
    parts = device_str.split("_")
    i = 0
    if i < len(parts) - 1 and re.match(r'^[A-Z]{2,5}$', parts[i]):
        i += 1
        if i < len(parts) - 1 and re.match(r'^[A-Z][A-Za-z]*\d+$', parts[i]):
            i += 1

    # Strip optional Modbus device-address keyword + numeric address (e.g. dev_100)
    # The type-instance that follows (e.g. EM-1) is part of the meter name — do not strip it
    if i < len(parts) - 1 and parts[i].lower() == "dev":
        i += 1  # skip "dev"
        if i < len(parts) - 1 and re.match(r'^\d+$', parts[i]):
            i += 1  # skip numeric address (e.g. "100")

    remaining_parts = parts[i:]
    if not remaining_parts:
        return None

    # Collapse repeated halves (DeviceName_DeviceName → DeviceName)
    n = len(remaining_parts)
    if n >= 2 and n % 2 == 0:
        half = n // 2
        first_half = "_".join(remaining_parts[:half])
        second_half = "_".join(remaining_parts[half:])
        if first_half.lower() == second_half.lower():
            return first_half

    result = "_".join(remaining_parts)
    return result if result else None


# Matches the standard BACnet network/channel prefix, e.g. "DP_Comm2_" or "UC_Comm0_"
_NET_PREFIX_RE = re.compile(r'^[A-Z]{2,5}_Comm\d+_', re.IGNORECASE)

# Broader prefix: matches any network code with optional Comm channel and
# optional Modbus dev block, with or without a Comm# segment.
# Used for the unmatched-suffix fallback to handle both Comm and non-Comm refs.
_ANY_PREFIX_RE = re.compile(
    r'^[A-Z]{2,5}_(?:[A-Z][A-Za-z]*\d+_)?(?:dev_\d+_)?',
    re.IGNORECASE,
)

# Matches a PascalCase gateway/aggregator segment between the network prefix
# and the meter name, e.g. "DataNab" in DP_Comm0_DataNab_{meter}.
# Requires at least one lowercase then another uppercase — rules out plain
# meter-name segments like MAIN, PV, or EM-1.
_GATEWAY_SEGMENT_RE = re.compile(r'^[A-Z][a-z]+[A-Z][a-zA-Z0-9]*$')


def _strip_prefix(device_str: str) -> Optional[str]:
    """
    Extended prefix stripper.  Calls _strip_and_deduplicate() then removes an
    optional PascalCase gateway segment (e.g. DataNab) if one remains at front.

    Handles DP_Comm0_DataNab_{meter_name}:
      _strip_and_deduplicate  -> "DataNab_MAIN_Meter"
      gateway strip           -> "MAIN_Meter"
    """
    result = _strip_and_deduplicate(device_str)
    if result is None:
        return None
    parts = result.split("_")
    if len(parts) > 1 and _GATEWAY_SEGMENT_RE.match(parts[0]):
        remainder = "_".join(parts[1:])
        return remainder if remainder else None
    return result


def _build_raw_lookup(meter_type: str):
    """
    Return (non_ignore_suffixes, ignore_key_set) built from the field map.

    non_ignore_suffixes: list of lowercased raw names sorted longest-first,
                         used to match point suffixes in refs.
    ignore_key_set:      set of lowercased raw names that map to IGNORE,
                         used to skip irrelevant points.
    """
    try:
        field_map = load_field_mapping(meter_type)
    except Exception:
        return [], set()

    non_ignore: set = set()
    ignore_set: set = set()
    for raw_name, standard_name in field_map.items():
        if standard_name == "IGNORE":
            ignore_set.add(raw_name.lower())
        else:
            non_ignore.add(raw_name.lower())

    return sorted(non_ignore, key=len, reverse=True), ignore_set


def extract_asset_name_from_refs(points: Dict[str, Any], meter_type: str) -> Optional[str]:
    """
    Extract meter device name by matching known field-map raw names against ref suffixes.

    Strategy:
      1. Skip IGNORE points (ping, Data_Stale, etc.) — their refs have a different
         structure that would produce bogus device-name candidates.
      2. Try every known non-IGNORE raw name (longest first) as a '_suffix' at the
         end of the FULL ref string.  The part before the suffix is the device_str;
         apply _strip_and_deduplicate() to get the device name.  This handles both
         standard refs (DP_CommN_Device_Field) and non-Comm refs where the device
         name is embedded twice (DP_Device_Device_Field).
      3. Vote across all points; return the plurality winner.
      4. Fallback: for refs that carry a standard CommN prefix but whose suffix isn't
         in the field map (e.g. GasFlowTotal, kW_01), collect all post-prefix remainders
         and return their longest common underscore-segment prefix as the device name.
         This correctly handles numbered sub-points (kW_01..42, kWh_01..42 → IDF1_2Raw01)
         as well as single-point devices where the full remainder IS the device name.
    """
    raw_suffixes, ignore_keys = _build_raw_lookup(meter_type)

    candidates: Dict[str, int] = {}
    fallback_remainders: List[str] = []

    for point_key, point_data in points.items():
        # 1. Skip IGNORE points
        if point_key.lower() in ignore_keys:
            continue

        ref = point_data.get("ref", "")
        if not ref:
            continue

        # 2. Match a known raw suffix against the full ref.
        #    Regex allows an optional trailing _\d+ so refs like _kW_01 match.
        matched = False
        for raw in raw_suffixes:
            pattern = r"_" + re.escape(raw) + r"(_\d+)?$"
            m = re.search(pattern, ref, re.IGNORECASE)
            if m:
                device_str = ref[: m.start()]
                device_name = _strip_prefix(device_str)
                if device_name:
                    candidates[device_name] = candidates.get(device_name, 0) + 1
                matched = True
                break

        # 4. Collect post-prefix remainders for unrecognised suffixes.
        #    Uses the broader _ANY_PREFIX_RE to handle both Comm and non-Comm
        #    refs (e.g. DP_Comm2_... and DP_...).  Also strips a PascalCase
        #    gateway segment (e.g. DataNab) from the remainder if present.
        if not matched:
            m = _ANY_PREFIX_RE.match(ref)
            if m:
                remainder = ref[m.end():]
                seg, _, rest = remainder.partition("_")
                if rest and _GATEWAY_SEGMENT_RE.match(seg):
                    remainder = rest
                if remainder:
                    fallback_remainders.append(remainder)

    # 3. Return plurality winner from primary candidates
    if candidates:
        return max(candidates, key=lambda k: candidates[k])

    if not fallback_remainders:
        return None

    # Longest common underscore-segment prefix across all fallback remainders
    parts_list = [r.split("_") for r in fallback_remainders]
    min_segs = min(len(p) for p in parts_list)
    common_len = 0
    for i in range(min_segs):
        seg = parts_list[0][i].lower()
        if all(p[i].lower() == seg for p in parts_list):
            common_len = i + 1
        else:
            break

    if common_len == 0:
        return None

    return "_".join(parts_list[0][:common_len])


def extract_name_from_single_ref(ref: str, suffix_list: list) -> Optional[str]:
    """
    Extract meter name from a single ref string.  Handles:
      DP_{meter}_{point}
      DP_Comm#_{meter}_{point}
      DP_Comm#_DataNab_{meter}_{point}  (PascalCase gateway segment)
      ..._{point}_\\d+                   (trailing numeric index)
      DP_Comm#_{meter}                   (no trailing point at all — fallback)
    """
    for raw in suffix_list:
        pattern = r"_" + re.escape(raw) + r"(_\d+)?$"
        m = re.search(pattern, ref, re.IGNORECASE)
        if m:
            device_str = ref[: m.start()]
            return _strip_prefix(device_str)

    # Fallback: no recognized suffix found.  If this looks like a valid BACnet
    # ref (starts with 2-5 uppercase letters + underscore), strip the network
    # prefix directly — the remainder is the meter name.
    if re.match(r'^[A-Z]{2,5}_', ref):
        return _strip_prefix(ref)
    return None


def build_yaml_asset_name(raw_name: str, meter_type: str) -> str:
    """Apply meter-type prefix: EM → power-meter-, WM/GM → utility-."""
    prefix = "power-meter" if meter_type == "EM" else "utility"
    return f"{prefix}-{raw_name}"


def run_site_model_editor() -> None:
    # --- Phase 1: Update site model JSON ---

    # 1. Get file path
    while True:
        file_path = input("Enter the path to the site model JSON file: ").strip().strip('"').strip("'")
        if os.path.isfile(file_path):
            break
        print(f"File not found: '{file_path}'")
        print("Tip: On Windows, you can right-click the file and use 'Copy as path', then paste here.")

    # 2. Load and validate
    try:
        parsed = load_site_model(file_path)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        return
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    if not validate_site_model(parsed):
        print("JSON validation failed.")
        return

    num_id = str(parsed.get("cloud", {}).get("num_id", ""))

    # 3. Get meter type and process points
    meter_type = input("Enter meter type (EM, WM, GM): ").strip().upper()
    try:
        ci_field_map = build_case_insensitive_field_map(meter_type)
        field_dbo_units = load_field_dbo_units(meter_type)
    except ValueError as e:
        print(e)
        return

    points = parsed["pointset"]["points"]
    yaml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mappings", "standard_field_map.yaml")
    all_to_skip: Set[str] = set()
    all_ignored: Set[str] = set()

    # 4. Review and resolve unmatched (retry loop for manual YAML edits)
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
    matched_fields = [k for k in updated_points]
    # print(f"\nMatched Standard Fields:\n{', '.join(matched_fields)}")

    confirm = input("\nContinue with these mappings? (Enter=Yes, 2=Skip): ").strip()
    if confirm == "2":
        print("Cancelled.")
        return

    # 5. Save updated JSON
    raw_name = extract_asset_name_from_refs(points, meter_type)
    if raw_name is None:
        raw_name = parsed.get("system", {}).get("name", "UNKNOWN")
        print(f"Could not extract asset name from refs, falling back to: {raw_name}")
    suggested = build_yaml_asset_name(raw_name, meter_type)
    sample_ref = next((p.get("ref") for p in points.values() if p.get("ref")), None)
    if sample_ref:
        print(f"\nSample ref: {sample_ref}")
    override = input(f"Asset name: [{suggested}] (press Enter to accept or type a new name): ").strip()
    asset_name = override if override else suggested
    site = parsed.get("system", {}).get("location", {}).get("site", "")
    auto_filename = f"{site}_{asset_name}" if site else asset_name

    default_dir = os.path.dirname(os.path.abspath(file_path))
    dir_input = input(f"\nEnter output directory (press Enter to use input file's folder):\n  [{default_dir}]: ").strip().strip('"').strip("'")
    save_dir = dir_input if dir_input else default_dir

    save_updated_json(parsed, updated_points, auto_filename, save_dir)
