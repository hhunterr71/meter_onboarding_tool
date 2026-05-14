"""
Validation script for extract_asset_name_from_refs.

Reads tests/pointset_refs.csv, groups by (building, device), reconstructs
a points dict from the ref column, runs the extractor, then checks that the
extracted device name is consistent with every non-ping ref for that device.

Usage:
    python tests/validate_meter_name_extraction.py          # standalone
    python -m pytest tests/validate_meter_name_extraction.py -v  # pytest
"""

import csv
import os
import sys
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Allow imports from the project root regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_model_editor import extract_asset_name_from_refs, _NET_PREFIX_RE

CSV_PATH = os.path.join(os.path.dirname(__file__), "pointset_refs.csv")

# Map the UDMI device-ID prefix to the field-map meter type
_PREFIX_TO_TYPE: Dict[str, str] = {
    "EM": "EM",
    "EMV": "EM",   # virtual/aggregate EM meters
    "PVI": "EM",   # PV inverters use the EM field map
    "WM": "WM",
    "GM": "GM",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_meter_type(device: str) -> str:
    prefix = device.split("-")[0]
    return _PREFIX_TO_TYPE.get(prefix, "EM")


def load_devices(csv_path: str) -> Dict[Tuple[str, str, str], Dict]:
    """
    Return {(building, device, meter_type): {point_key: {"ref": ref_str}}}.
    The point key comes directly from the 'point' column (may already be
    a standard field name or a raw name — the extractor handles both).
    """
    devices: Dict = defaultdict(dict)
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["building"], row["device"], _infer_meter_type(row["device"]))
            devices[key][row["point"]] = {"ref": row["ref"]}
    return devices


def check_consistency(
    extracted: str,
    points: Dict,
) -> Tuple[int, int, List[Tuple[str, str, str]]]:
    """
    For every ref that matches the standard BACnet prefix pattern (i.e. NOT a
    ping/monitor ref), verify that the device portion starts with `extracted`.

    Returns (matched, total_checked, [(point_key, ref, remaining), ...] failures).
    """
    matched = 0
    checked = 0
    failures = []
    name_lower = extracted.lower()

    for point_key, point_data in points.items():
        ref = point_data.get("ref", "")
        m = _NET_PREFIX_RE.match(ref)
        if not m:
            continue  # ping / MONITOR refs — skip
        remaining = ref[m.end():]          # e.g. "MAIN_Meter_kWh"
        remaining_lower = remaining.lower()
        checked += 1

        # Device name must be exactly `extracted` OR `extracted` followed by `_<something>`
        if remaining_lower == name_lower or remaining_lower.startswith(name_lower + "_"):
            matched += 1
        else:
            failures.append((point_key, ref, remaining))

    return matched, checked, failures


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def run_validation(verbose: bool = True) -> bool:
    devices = load_devices(CSV_PATH)
    total = len(devices)
    n_passed = 0
    n_failed = 0
    failure_summary: List[Dict] = []

    for (building, device, meter_type), points in sorted(devices.items()):
        extracted = extract_asset_name_from_refs(points, meter_type)
        label = f"[{building}] {device:<12}"

        if extracted is None:
            n_failed += 1
            failure_summary.append({
                "label": label,
                "reason": "No name extracted",
                "failures": [],
            })
            if verbose:
                print(f"  FAIL  {label}  -> (no name extracted)")
            continue

        matched, checked, failures = check_consistency(extracted, points)

        if checked == 0:
            # Only ping refs exist — nothing to validate against
            if verbose:
                print(f"  WARN  {label}  -> '{extracted}'  (no non-ping refs to validate)")
            n_passed += 1
            continue

        if not failures:
            n_passed += 1
            if verbose:
                print(f"  PASS  {label}  -> '{extracted}'  ({matched}/{checked} refs)")
        else:
            n_failed += 1
            reason = f"{len(failures)}/{checked} refs don't contain the extracted name"
            failure_summary.append({
                "label": label,
                "extracted": extracted,
                "reason": reason,
                "failures": failures,
            })
            if verbose:
                print(f"  FAIL  {label}  -> '{extracted}'  ({matched}/{checked} match — {len(failures)} mismatches)")
                for point_key, ref, remaining in failures[:3]:
                    print(f"          point : {point_key}")
                    print(f"          ref   : {ref}")
                    print(f"          after prefix: {remaining}")
                if len(failures) > 3:
                    print(f"          ... and {len(failures) - 3} more")

    # Summary
    if verbose:
        sep = "=" * 64
        print(f"\n{sep}")
        print(f"  {n_passed}/{total} PASSED    {n_failed} FAILED")
        print(sep)

        if failure_summary:
            print("\nFailed devices:")
            for case in failure_summary:
                name = case.get("extracted", "(none)")
                print(f"  {case['label']}  '{name}'  — {case['reason']}")

    return n_failed == 0


# ---------------------------------------------------------------------------
# pytest entry point
# ---------------------------------------------------------------------------

def test_meter_name_extraction() -> None:
    """All devices in pointset_refs.csv must produce a consistent extracted name."""
    assert run_validation(verbose=True), (
        "One or more devices failed meter name extraction — see output above."
    )


if __name__ == "__main__":
    success = run_validation(verbose=True)
    sys.exit(0 if success else 1)
