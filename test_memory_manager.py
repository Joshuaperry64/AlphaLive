import unittest
import sqlite3
import os
import tempfile
from pathlib import Path
from memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary database for testing
        self.test_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.test_dir.name) / "test_memory.db"
        self.mm = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        # Clean up
        self.test_dir.cleanup()

    def test_update_personality_insert(self):
        # Test inserting a new trait
        result = self.mm.update_personality("test_trait", "test_value")
        self.assertTrue(result)

        # Verify it was inserted
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("test_trait"), "test_value")

    def test_update_personality_update(self):
        # Insert first
        self.mm.update_personality("test_trait", "test_value")

        # Update existing trait
        result = self.mm.update_personality("test_trait", "new_value")
        self.assertTrue(result)

        # Verify it was updated
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("test_trait"), "new_value")

    def test_update_personality_strips_whitespace(self):
        # Test whitespace stripping
        result = self.mm.update_personality("  spaced_trait  ", "  spaced_value  ")
        self.assertTrue(result)

        # Verify whitespace was stripped
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("spaced_trait"), "spaced_value")

    def test_update_personality_error_handling(self):
        # Force an error by passing a bad type (e.g. mock the connection to fail)
        # Using a read-only database path or messing with the table structure

        # Delete the table to force an SQL error
        with self.mm._get_conn() as conn:
            conn.execute('DROP TABLE core_identity')
            conn.commit()

        result = self.mm.update_personality("test", "value")
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
