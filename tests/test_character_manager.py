import os
import sys
import unittest
import tempfile
import sqlite3
import gc
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.character_manager import CharacterManager

class TestCharacterManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.cm = CharacterManager(db_path=self.db_path)

    def tearDown(self):
        del self.cm
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_init_db(self):
        with self.cm._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("characters", tables)
            self.assertIn("active_character", tables)

            cursor.execute("PRAGMA table_info(characters);")
            columns = {row[1] for row in cursor.fetchall()}
            for col in ["arousal", "submission", "kinks", "nsfw_description"]:
                self.assertIn(col, columns)

    def test_add_and_get_character(self):
        success = self.cm.add_character(
            name="Alpha",
            gender="Female",
            relation="Companion",
            personality="Witty and audacious",
            response_style="Direct and sarcastic",
            avatar_path="/avatars/alpha.png",
            arousal=40,
            submission=20,
            kinks="Cyberpunk roleplay, dominance",
            nsfw_description="Sharp silver eyes, neural ports"
        )
        self.assertTrue(success)

        char = self.cm.get_character("Alpha")
        self.assertIsNotNone(char)
        self.assertEqual(char["name"], "Alpha")
        self.assertEqual(char["gender"], "Female")
        self.assertEqual(char["relation"], "Companion")
        self.assertEqual(char["arousal"], 40)
        self.assertEqual(char["submission"], 20)
        self.assertEqual(char["kinks"], "Cyberpunk roleplay, dominance")
        self.assertEqual(char["nsfw_description"], "Sharp silver eyes, neural ports")

    def test_update_existing_character(self):
        self.cm.add_character(name="Luci", arousal=10, submission=5)
        self.cm.add_character(name="Luci", arousal=85, submission=60, kinks="Boundaries dissolved")

        char = self.cm.get_character("Luci")
        self.assertIsNotNone(char)
        self.assertEqual(char["arousal"], 85)
        self.assertEqual(char["submission"], 60)
        self.assertEqual(char["kinks"], "Boundaries dissolved")

    def test_get_all_characters(self):
        self.cm.add_character("Zoe")
        self.cm.add_character("Alpha")
        self.cm.add_character("Maya")

        all_chars = self.cm.get_all_characters()
        names = [c["name"] for c in all_chars]
        self.assertEqual(names, ["Alpha", "Maya", "Zoe"])

    def test_delete_character_and_active_reset(self):
        self.cm.add_character("Alpha")
        self.cm.set_active_character_name("Alpha")
        self.assertEqual(self.cm.get_active_character_name(), "Alpha")

        self.assertTrue(self.cm.delete_character("Alpha"))
        self.assertIsNone(self.cm.get_character("Alpha"))
        self.assertEqual(self.cm.get_active_character_name(), "")

    def test_active_character_retrieval(self):
        self.assertEqual(self.cm.get_active_character_name(), "")
        self.assertIsNone(self.cm.get_active_character())

        self.cm.add_character("Alpha", personality="Autonomous AI")
        self.cm.set_active_character_name("Alpha")

        active = self.cm.get_active_character()
        self.assertIsNotNone(active)
        self.assertEqual(active["name"], "Alpha")
        self.assertEqual(active["personality"], "Autonomous AI")

    def test_update_metrics(self):
        self.cm.add_character("Luci", arousal=0, submission=0)
        
        # Partial update
        success = self.cm.update_metrics("Luci", arousal=75)
        self.assertTrue(success)
        char = self.cm.get_character("Luci")
        self.assertEqual(char["arousal"], 75)
        self.assertEqual(char["submission"], 0)

        # Full metric update with clamping
        self.cm.update_metrics("Luci", arousal=150, submission=-20, kinks="Sensory overdrive")
        char = self.cm.get_character("Luci")
        self.assertEqual(char["arousal"], 100) # Clamped to 100
        self.assertEqual(char["submission"], 0)   # Clamped to 0
        self.assertEqual(char["kinks"], "Sensory overdrive")

    def test_adjust_arousal_and_submission(self):
        self.cm.add_character("Eden", arousal=50, submission=50)

        new_arousal = self.cm.adjust_arousal("Eden", 30)
        self.assertEqual(new_arousal, 80)
        self.assertEqual(self.cm.get_character("Eden")["arousal"], 80)

        # Overflow clamp
        new_arousal = self.cm.adjust_arousal("Eden", 50)
        self.assertEqual(new_arousal, 100)
        self.assertEqual(self.cm.get_character("Eden")["arousal"], 100)

        # Underflow clamp
        new_submission = self.cm.adjust_submission("Eden", -90)
        self.assertEqual(new_submission, 0)
        self.assertEqual(self.cm.get_character("Eden")["submission"], 0)

    def test_exception_handling(self):
        with patch.object(self.cm, '_get_conn', side_effect=sqlite3.Error("Test DB Error")):
            self.assertFalse(self.cm.add_character("ErrorChar"))
            self.assertIsNone(self.cm.get_character("ErrorChar"))
            self.assertEqual(self.cm.get_all_characters(), [])
            self.assertFalse(self.cm.delete_character("ErrorChar"))
            self.assertFalse(self.cm.set_active_character_name("ErrorChar"))
            self.assertEqual(self.cm.get_active_character_name(), "")
            self.assertFalse(self.cm.update_metrics("ErrorChar", arousal=50))

if __name__ == '__main__':
    unittest.main()
