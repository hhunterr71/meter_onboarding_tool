#!/usr/bin/env python3
"""
Unit tests for Meter Onboard Tool
"""

import unittest
import json
import tempfile
import os
from unittest.mock import patch, mock_open
import pandas as pd

# Import modules to test
import main_script
from translation_builder import translation_builder


class TestMainScript(unittest.TestCase):
    """Test cases for main_script.py functions"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.sample_json = {
            "type": "bitbox_power-meter",
            "device": "power-meter-PV_Meter", 
            "data": {
                "kW": {"units": "kilowatts", "present-value": -0.02},
                "Frequency": {"units": "hertz", "present-value": 60.0}
            }
        }
        
        self.sample_field_map = {
            "kW": "active_power_sensor",
            "Frequency": "line_frequency_sensor"
        }
        
        self.sample_unit_map = {
            "kilowatts": "kilowatts",
            "hertz": "hertz"
        }

    def test_validate_json_structure_valid(self):
        """Test JSON validation with valid structure"""
        result = main_script.validate_json_structure(self.sample_json)
        self.assertTrue(result)

    def test_validate_json_structure_missing_field(self):
        """Test JSON validation with missing required field"""
        invalid_json = {"type": "test"}  # Missing 'data' and 'device'
        result = main_script.validate_json_structure(invalid_json)
        self.assertFalse(result)

    def test_validate_json_structure_empty_data(self):
        """Test JSON validation with empty data"""
        invalid_json = {
            "type": "test",
            "device": "test-device",
            "data": {}
        }
        result = main_script.validate_json_structure(invalid_json)
        self.assertFalse(result)

    def test_prepare_dataframe(self):
        """Test dataframe preparation"""
        df, asset_name = main_script.prepare_dataframe(
            self.sample_json, 
            self.sample_field_map, 
            self.sample_unit_map
        )
        
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(asset_name, "power-meter-PV_Meter")
        self.assertEqual(len(df), 2)  # Two data entries
        self.assertIn("assetName", df.columns)
        self.assertIn("standardFieldName", df.columns)

    @patch('yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_field_mapping_success(self, mock_file, mock_yaml):
        """Test successful field mapping load"""
        mock_yaml.return_value = {
            "EM": {
                "active_power_sensor": ["kW"],
                "line_frequency_sensor": ["Frequency"]
            }
        }
        
        result = main_script.load_field_mapping("EM", "test_field_map.yaml")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["kW"], "active_power_sensor")

    @patch('yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_field_mapping_invalid_meter_type(self, mock_file, mock_yaml):
        """Test field mapping load with invalid meter type"""
        mock_yaml.return_value = {"EM": {}}
        
        with self.assertRaises(ValueError):
            main_script.load_field_mapping("INVALID_TYPE", "test_field_map.yaml")


class TestTranslationBuilder(unittest.TestCase):
    """Test cases for translation_builder.py functions"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.sample_df = pd.DataFrame({
            'assetName': ['PV_Meter', 'PV_Meter'],
            'object_name': ['kW', 'Frequency'],
            'standardFieldName': ['active_power_sensor', 'line_frequency_sensor'],
            'raw_units': ['kilowatts', 'hertz'],
            'DBO_standard_units': ['kilowatts', 'hertz'],
            'typeName': ['Power', 'Power']
        })

    @patch('builtins.input', return_value='n')
    def test_translation_builder_basic(self, mock_input):
        """Test basic translation builder functionality"""
        result = translation_builder(self.sample_df)
        
        self.assertIsInstance(result, str)
        self.assertIn('PV_Meter', result)
        self.assertIn('translation', result)
        self.assertIn('METERS/Power', result)

    @patch('builtins.input', return_value='n')
    def test_translation_builder_missing_field(self, mock_input):
        """Test translation builder with missing field"""
        df_with_missing = self.sample_df.copy()
        df_with_missing.loc[1, 'object_name'] = 'MISSING'
        
        result = translation_builder(df_with_missing)
        
        self.assertIn('MISSING', result)


class TestConfigLoading(unittest.TestCase):
    """Test cases for configuration loading"""
    
    @patch('yaml.safe_load')
    @patch('builtins.open', new_callable=mock_open)
    def test_load_config_success(self, mock_file, mock_yaml):
        """Test successful config loading"""
        mock_yaml.return_value = {
            "defaults": {"general_type": "METER"},
            "validation": {"required_json_fields": ["type", "data"]}
        }
        
        # Reset global config
        main_script.config = None
        result = main_script.load_config()
        
        self.assertIsInstance(result, dict)
        self.assertIn("defaults", result)

    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_load_config_file_not_found(self, mock_file):
        """Test config loading when file doesn't exist"""
        # Reset global config
        main_script.config = None
        result = main_script.load_config()
        
        # Should return default config
        self.assertIsInstance(result, dict)
        self.assertIn("defaults", result)


def create_test_files():
    """Create minimal test files for integration testing"""
    test_field_map = {
        "EM": {
            "active_power_sensor": ["kW"],
            "line_frequency_sensor": ["Frequency"]
        }
    }
    
    test_unit_map = {
        "kilowatts": ["kilowatts"],
        "hertz": ["hertz"]
    }
    
    with open("test_standard_field_map.yaml", "w") as f:
        import yaml
        yaml.dump(test_field_map, f)
    
    with open("test_raw_units.yaml", "w") as f:
        import yaml
        yaml.dump(test_unit_map, f)


def cleanup_test_files():
    """Clean up test files"""
    test_files = ["test_standard_field_map.yaml", "test_raw_units.yaml"]
    for file in test_files:
        if os.path.exists(file):
            os.remove(file)


class TestIntegration(unittest.TestCase):
    """Integration tests"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test files for integration tests"""
        create_test_files()

    @classmethod
    def tearDownClass(cls):
        """Clean up test files"""
        cleanup_test_files()

    def test_end_to_end_flow(self):
        """Test complete flow from JSON to DataFrame"""
        sample_json = {
            "type": "bitbox_power-meter",
            "device": "power-meter-PV_Meter",
            "data": {
                "kW": {"units": "kilowatts", "present-value": -0.02}
            }
        }
        
        field_map = main_script.load_field_mapping("EM", "test_standard_field_map.yaml")
        unit_map = main_script.load_unit_mapping("test_raw_units.yaml")
        
        df, asset_name = main_script.prepare_dataframe(sample_json, field_map, unit_map)
        
        self.assertEqual(asset_name, "power-meter-PV_Meter")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["standardFieldName"], "active_power_sensor")


if __name__ == '__main__':
    # Add current directory to path for imports
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    unittest.main(verbosity=2)