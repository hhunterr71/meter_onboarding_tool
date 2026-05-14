#!/usr/bin/env python3
"""
Unit tests for Meter Onboard Tool
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, mock_open

import field_map_utils


class TestFieldMapUtils(unittest.TestCase):
    """Tests for field_map_utils field loading functions."""

    @patch('field_map_utils.yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_field_mapping_success(self, mock_file, mock_yaml):
        mock_yaml.return_value = {
            "EM": {
                "active_power_sensor": {
                    "dbo_unit": "kilowatts",
                    "standard_unit": "kilowatts",
                    "names": ["kW"],
                },
                "line_frequency_sensor": {
                    "dbo_unit": "hertz",
                    "standard_unit": "hertz",
                    "names": ["Frequency"],
                },
            }
        }
        result = field_map_utils.load_field_mapping("EM", "test_field_map.yaml")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["kW"], "active_power_sensor")

    @patch('field_map_utils.yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_field_mapping_invalid_meter_type(self, mock_file, mock_yaml):
        mock_yaml.return_value = {"EM": {}}
        with self.assertRaises(ValueError):
            field_map_utils.load_field_mapping("INVALID_TYPE", "test_field_map.yaml")

if __name__ == '__main__':
    unittest.main(verbosity=2)
