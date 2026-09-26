import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import unittest
from unittest.mock import patch, mock_open, MagicMock

class TestLoadConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Mock OS and ctypes things which might fail in headless or during import
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'

        # Save original sys.modules
        cls.original_modules = sys.modules.copy()

        # Mock required modules before importing gui
        sys.modules['pyautogui'] = MagicMock()
        sys.modules['dotenv'] = MagicMock()
        sys.modules['memory_manager'] = MagicMock()
        sys.modules['PyQt6'] = MagicMock()
        sys.modules['PyQt6.QtWidgets'] = MagicMock()
        sys.modules['PyQt6.QtCore'] = MagicMock()
        sys.modules['PyQt6.QtGui'] = MagicMock()

        # Import gui locally to avoid polluting global scope as much as possible
        global gui
        from ui import gui

    @classmethod
    def tearDownClass(cls):
        # Restore sys.modules
        sys.modules.clear()
        sys.modules.update(cls.original_modules)

    def setUp(self):
        # We need a stable DEFAULT_CONFIG for testing
        self.original_default = gui.DEFAULT_CONFIG
        gui.DEFAULT_CONFIG = {
            "Global": {"ApiKey": "123", "Session": "test"},
            "alpha_core.py": {"AudioMode": "half"}
        }

    def tearDown(self):
        gui.DEFAULT_CONFIG = self.original_default

    @patch('pathlib.Path.exists')
    def test_load_config_not_exists(self, mock_exists):
        mock_exists.return_value = False
        config = gui.load_config()
        self.assertEqual(config, gui.DEFAULT_CONFIG)
        self.assertIsNot(config, gui.DEFAULT_CONFIG) # Should be a copy

    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="invalid json")
    def test_load_config_invalid_json(self, mock_file, mock_exists):
        mock_exists.return_value = True
        config = gui.load_config()
        self.assertEqual(config, gui.DEFAULT_CONFIG)

    @patch('pathlib.Path.exists')
    def test_load_config_valid_json_with_missing_defaults(self, mock_exists):
        mock_exists.return_value = True
        saved_data = {
            "Global": {"Session": "custom_session"}
        }
        with patch('builtins.open', mock_open(read_data=json.dumps(saved_data))):
            config = gui.load_config()

        expected = {
            "Global": {"ApiKey": "123", "Session": "custom_session"},
            "alpha_core.py": {"AudioMode": "half"}
        }
        self.assertEqual(config, expected)

if __name__ == '__main__':
    unittest.main()
