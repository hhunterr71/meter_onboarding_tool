"""
Processes a raw pointset_refs.xlsx (from site_model_ref_compiler.py) in two passes:

  Pass 1 — Field map matching:
    Matches each point name against standard_field_map.yaml and assigns a
    dbo_point (standard field name) and flag (IGNORE / not in standard field map).

  Pass 2 — Meter name extraction validation:
    For each non-IGNORE ref, attempts to extract the meter device name using
    the field-map suffix approach.  Handles trailing _\\d+ indices and
    PascalCase gateway segments (e.g. DataNab).

Usage:
    python tests/ref_extraction_validator.py
    python tests/ref_extraction_validator.py path/to/pointset_refs.xlsx

Output: ref_extraction_results.xlsx (written next to the input file)
  Tab 1 "Raw Points"       — passthrough from input
  Tab 2 "Field Map Match"  — + dbo_point and flag columns
  Tab 3 "Not In Field Map" — distinct (meter_type, point) with no match
  Tab 4 "Per Device"       — per-device extraction result
  Tab 5 "Failures"         — refs where no suffix matched at all
"""

import os
import sys
from collections import defaultdict

import pandas as pd

# ---------------------------------------------------------------------------
# Project root on the path so project modules are importable
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from site_model_editor import (  # noqa: E402
    _build_raw_lookup,
    extract_name_from_single_ref,
)
from field_map_utils import _load_field_map_yaml                          # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_INPUT = os.path.join(os.path.dirname(__file__), "pointset_refs.xlsx")
OUTPUT_FILENAME = "ref_extraction_results.xlsx"


# ---------------------------------------------------------------------------
# Field map helpers (Pass 1)
# ---------------------------------------------------------------------------

def _build_field_lookups(all_mappings: dict) -> dict:
    """
    Return {meter_type: (name_to_standard, ignore_names)} for every meter type
    in the YAML.  name_to_standard maps lowercased raw names to their DBO
    standard field name.  ignore_names is a set of lowercased raw names that
    should be flagged IGNORE.
    """
    lookups = {}
    for meter_type, fields in all_mappings.items():
        name_to_standard = {}
        ignore_names = set()
        for standard_field, field_data in fields.items():
            names = field_data.get("names") or []
            if standard_field == "IGNORE":
                for n in names:
                    ignore_names.add(n.lower())
            else:
                for n in names:
                    name_to_standard[n.lower()] = standard_field
                # Allow already-DBO-named points to match themselves
                name_to_standard[standard_field.lower()] = standard_field
        lookups[meter_type] = (name_to_standard, ignore_names)
    return lookups


def _match_point(point_name: str, meter_type: str, lookups: dict):
    """Return (dbo_point, flag) for a single point."""
    name_to_standard, ignore_names = lookups.get(meter_type, ({}, set()))
    point_lower = point_name.lower()
    if point_lower in ignore_names:
        return "", "IGNORE"
    if point_lower in name_to_standard:
        return name_to_standard[point_lower], ""
    return "", "not in standard field map"



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
    else:
        default = DEFAULT_INPUT
        answer = input(f"Path to pointset_refs.xlsx [{default}]: ").strip().strip('"').strip("'")
        input_path = answer if answer else default

    if not os.path.isfile(input_path):
        print(f"ERROR: file not found: {input_path}")
        sys.exit(1)

    output_file = os.path.join(os.path.dirname(os.path.abspath(input_path)), OUTPUT_FILENAME)

    print(f"Reading {input_path} ...")
    df_raw = pd.read_excel(input_path, dtype=str).fillna("")

    required = {"building", "device", "meter_type", "point", "ref"}
    missing = required - set(df_raw.columns)
    if missing:
        print(f"ERROR: missing columns: {missing}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Pass 1: field map matching
    # ------------------------------------------------------------------
    all_mappings = _load_field_map_yaml()
    lookups = _build_field_lookups(all_mappings)

    dbo_points = []
    flags = []
    for _, row in df_raw.iterrows():
        if not row["ref"]:
            dbo_points.append("")
            flags.append("")
            continue
        dbo_point, flag = _match_point(row["point"], row["meter_type"], lookups)
        dbo_points.append(dbo_point)
        flags.append(flag)

    df_matched = df_raw.copy()
    df_matched["dbo_point"] = dbo_points
    df_matched["flag"] = flags

    df_not_in_map = (
        df_matched[df_matched["flag"] == "not in standard field map"][["meter_type", "point"]]
        .drop_duplicates()
        .sort_values(["meter_type", "point"])
        .reset_index(drop=True)
    )

    # ------------------------------------------------------------------
    # Pass 2: meter name extraction
    # ------------------------------------------------------------------
    suffix_lists = {mt: _build_raw_lookup(mt)[0] for mt in df_matched["meter_type"].unique() if mt}

    extracted_names = []
    for _, row in df_matched.iterrows():
        if row["flag"] == "IGNORE" or not row["ref"]:
            extracted_names.append("")
            continue
        name = extract_name_from_single_ref(row["ref"], suffix_lists.get(row["meter_type"], []))
        extracted_names.append(name or "")

    df_matched["extracted_name"] = extracted_names

    # ------------------------------------------------------------------
    # Per-device voting & consistency
    # ------------------------------------------------------------------
    device_vote: dict = defaultdict(lambda: defaultdict(int))
    device_meta: dict = {}
    device_total: dict = defaultdict(int)

    for _, row in df_matched.iterrows():
        if row["flag"] == "IGNORE" or not row["ref"]:
            continue
        key = (row["building"], row["device"])
        device_meta[key] = row["meter_type"]
        device_total[key] += 1
        # Only vote using field-map-matched points.  Refs whose point name is
        # not in the field map hit the extraction fallback and include the raw
        # point suffix in the result, which would cause false INCONSISTENT.
        if row["extracted_name"] and row["flag"] == "":
            device_vote[key][row["extracted_name"]] += 1

    per_device_rows = []
    for key in sorted(device_meta):
        building, device = key
        vote = device_vote.get(key, {})
        total = device_total[key]

        if not vote:
            winner, matched, result = "", 0, "FAILED"
        else:
            winner = max(vote, key=lambda k: vote[k])
            matched = vote[winner]
            result = "OK" if len(vote) == 1 else "INCONSISTENT"

        per_device_rows.append({
            "building": building,
            "device": device,
            "meter_type": device_meta[key],
            "extracted_name": winner,
            "matched_refs": matched,
            "total_refs": total,
            "result": result,
        })

    df_devices = pd.DataFrame(per_device_rows)

    df_failures = df_matched[
        (df_matched["extracted_name"] == "") &
        (df_matched["flag"] != "IGNORE") &
        (df_matched["ref"] != "")
    ][["building", "device", "meter_type", "point", "ref", "flag"]].copy()

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    # Tab 2 columns: raw columns + dbo_point + flag (drop extracted_name — that's for Tab 4/5)
    tab2_cols = list(df_raw.columns) + ["dbo_point", "flag"]
    df_tab2 = df_matched[tab2_cols]

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df_raw.to_excel(writer, sheet_name="Raw Points", index=False)
        df_tab2.to_excel(writer, sheet_name="Field Map Match", index=False)
        df_not_in_map.to_excel(writer, sheet_name="Not In Field Map", index=False)
        df_devices.to_excel(writer, sheet_name="Per Device", index=False)
        df_failures.to_excel(writer, sheet_name="Failures", index=False)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    n_total = len(df_devices)
    n_ok = (df_devices["result"] == "OK").sum()
    n_inconsistent = (df_devices["result"] == "INCONSISTENT").sum()
    n_failed = (df_devices["result"] == "FAILED").sum()
    pct = 100 * n_ok / n_total if n_total else 0

    print(f"\nField map:  {len(df_matched)} rows matched")
    print(f"  Mapped              : {(df_matched['flag'] == '').sum()}")
    print(f"  IGNORE              : {(df_matched['flag'] == 'IGNORE').sum()}")
    print(f"  Not in field map    : {(df_matched['flag'] == 'not in standard field map').sum()}")
    print(f"  Distinct unmatched  : {len(df_not_in_map)}")

    print(f"\nExtraction: {n_total} devices")
    print(f"  OK          : {n_ok}  ({pct:.1f}%)")
    print(f"  INCONSISTENT: {n_inconsistent}")
    print(f"  FAILED      : {n_failed}")
    print(f"  Unmatched refs (no suffix): {len(df_failures)}")

    print(f"\nWrote {output_file}")
    for name, sheet_df in [
        ("Raw Points", df_raw),
        ("Field Map Match", df_tab2),
        ("Not In Field Map", df_not_in_map),
        ("Per Device", df_devices),
        ("Failures", df_failures),
    ]:
        print(f"  '{name}': {len(sheet_df)} rows")


if __name__ == "__main__":
    main()
