import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.manager = MemoryManager(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_db(self):
        # Verify that tables are created
        with self.manager._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertTrue("core_identity" in tables)
            self.assertTrue("knowledge_graph" in tables)
            self.assertTrue("episodic_memory" in tables)

    # --- Core Identity Tests ---

    def test_update_and_get_personality(self):
        result = self.manager.update_personality("humor", "high")
        self.assertTrue(result)

        personality = self.manager.get_personality()
        self.assertEqual(personality.get("humor"), "high")

    def test_update_personality_conflict(self):
        self.manager.update_personality("humor", "low")
        self.manager.update_personality("humor", "high")
        personality = self.manager.get_personality()
        self.assertEqual(personality.get("humor"), "high")

    def test_get_personality_details(self):
        self.manager.update_personality("humor", "high")
        details = self.manager.get_personality_details()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["trait_name"], "humor")
        self.assertEqual(details[0]["trait_value"], "high")
        self.assertIn("updated_at", details[0])

    def test_delete_personality(self):
        self.manager.update_personality("humor", "high")
        self.manager.delete_personality("humor")
        personality = self.manager.get_personality()
        self.assertNotIn("humor", personality)

    def test_personality_exceptions(self):
        with patch.object(self.manager, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.manager.update_personality("humor", "high"))
            self.assertEqual(self.manager.get_personality(), {})
            self.assertEqual(self.manager.get_personality_details(), [])
            self.assertFalse(self.manager.delete_personality("humor"))

    # --- Knowledge Graph Tests ---

    def test_memorize_and_recall_fact(self):
        result = self.manager.memorize_fact("josh", "likes", "pizza")
        self.assertTrue(result)

        facts = self.manager.recall_knowledge("josh")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["subject"], "josh")
        self.assertEqual(facts[0]["predicate"], "likes")
        self.assertEqual(facts[0]["object"], "pizza")

    def test_get_all_facts(self):
        self.manager.memorize_fact("josh", "likes", "pizza")
        self.manager.memorize_fact("alice", "likes", "sushi")
        facts = self.manager.get_all_facts()
        self.assertEqual(len(facts), 2)

    def test_search_knowledge(self):
        self.manager.memorize_fact("josh", "likes", "pizza")
        self.manager.memorize_fact("alice", "likes", "sushi")
        results = self.manager.search_knowledge("pizza")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["subject"], "josh")

    def test_delete_fact(self):
        self.manager.memorize_fact("josh", "likes", "pizza")
        facts = self.manager.recall_knowledge("josh")
        fact_id = facts[0]["id"]

        result = self.manager.delete_fact(fact_id)
        self.assertTrue(result)

        facts_after = self.manager.recall_knowledge("josh")
        self.assertEqual(len(facts_after), 0)

    def test_knowledge_graph_exceptions(self):
        with patch.object(self.manager, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.manager.memorize_fact("josh", "likes", "pizza"))
            self.assertEqual(self.manager.get_all_facts(), [])
            self.assertEqual(self.manager.recall_knowledge("josh"), [])
            self.assertEqual(self.manager.search_knowledge("pizza"), [])
            self.assertFalse(self.manager.delete_fact(1))

    # --- Episodic Memory Tests ---

    def test_write_and_get_diary_entry(self):
        result = self.manager.write_diary_entry("Had a great day!", "session_1", 0.9)
        self.assertTrue(result)

        episodes = self.manager.get_recent_episodes()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["content"], "Had a great day!")
        self.assertEqual(episodes[0]["session_name"], "session_1")
        self.assertEqual(episodes[0]["sentiment_score"], 0.9)
        self.assertEqual(episodes[0]["event_type"], "diary")

    def test_delete_episode(self):
        self.manager.write_diary_entry("Had a great day!")
        episodes = self.manager.get_recent_episodes()
        episode_id = episodes[0]["id"]

        result = self.manager.delete_episode(episode_id)
        self.assertTrue(result)

        episodes_after = self.manager.get_recent_episodes()
        self.assertEqual(len(episodes_after), 0)

    def test_episodic_memory_exceptions(self):
        with patch.object(self.manager, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.manager.write_diary_entry("Had a great day!"))
            self.assertEqual(self.manager.get_recent_episodes(), [])
            self.assertFalse(self.manager.delete_episode(1))

if __name__ == '__main__':
    unittest.main()
