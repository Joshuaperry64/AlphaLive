import os
import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch
from memory.memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.mm = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_init_db(self):
        # Verify that tables are created
        with self.mm._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertTrue("core_identity" in tables)
            self.assertTrue("knowledge_graph" in tables)
            self.assertTrue("episodic_memory" in tables)

    # ── Knowledge Graph Tests ─────────────────────────────────────────────────

    def test_memorize_fact_success(self):
        result = self.mm.memorize_fact("josh", "likes", "cyberpunk")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("josh")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['subject'], "josh")
        self.assertEqual(facts[0]['predicate'], "likes")
        self.assertEqual(facts[0]['object'], "cyberpunk")

    def test_memorize_fact_strips_and_lowercases(self):
        result = self.mm.memorize_fact("  JOSH  ", " LiKeS ", " CyberPunk   ")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("josh")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['subject'], "josh")
        self.assertEqual(facts[0]['predicate'], "likes")
        self.assertEqual(facts[0]['object'], "cyberpunk")

    def test_memorize_fact_default_source(self):
        result = self.mm.memorize_fact("josh", "likes", "cyberpunk")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("josh")
        self.assertEqual(facts[0]['source'], "conversation")

    def test_memorize_fact_custom_source(self):
        result = self.mm.memorize_fact("josh", "likes", "cyberpunk", source="system_prompt")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("josh")
        self.assertEqual(facts[0]['source'], "system_prompt")

    @patch.object(MemoryManager, '_get_conn')
    def test_memorize_fact_exception_handling(self, mock_get_conn):
        mock_get_conn.side_effect = sqlite3.Error("Test DB Error")
        result = self.mm.memorize_fact("josh", "likes", "cyberpunk")
        self.assertFalse(result)

    def test_recall_knowledge_returns_facts(self):
        self.mm.memorize_fact("test_subject", "is_a", "test")
        self.mm.memorize_fact("test_subject", "has", "value")
        self.mm.memorize_fact("other_subject", "is", "ignored")

        facts = self.mm.recall_knowledge("test_subject")
        self.assertEqual(len(facts), 2)
        predicates = [f['predicate'] for f in facts]
        self.assertIn("is_a", predicates)
        self.assertIn("has", predicates)

    def test_recall_knowledge_empty_for_missing_subject(self):
        self.mm.memorize_fact("some_subject", "has", "value")
        facts = self.mm.recall_knowledge("nonexistent_subject")
        self.assertEqual(facts, [])

    def test_recall_knowledge_case_and_whitespace_insensitivity(self):
        self.mm.memorize_fact("  Mixed Case Subject  ", "is", "test")
        facts1 = self.mm.recall_knowledge("mixed case subject")
        facts2 = self.mm.recall_knowledge(" MIXED CASE SUBJECT ")
        facts3 = self.mm.recall_knowledge("MiXeD CaSe SuBjEcT")
        self.assertEqual(len(facts1), 1)
        self.assertEqual(len(facts2), 1)
        self.assertEqual(len(facts3), 1)

    def test_get_all_facts(self):
        self.mm.memorize_fact("josh", "likes", "pizza")
        self.mm.memorize_fact("alice", "likes", "sushi")
        facts = self.mm.get_all_facts()
        self.assertEqual(len(facts), 2)

    def test_search_knowledge(self):
        self.mm.memorize_fact("josh", "likes", "pizza")
        self.mm.memorize_fact("alice", "likes", "sushi")
        results = self.mm.search_knowledge("pizza")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["subject"], "josh")

    def test_delete_fact(self):
        self.mm.memorize_fact("josh", "likes", "pizza")
        facts = self.mm.recall_knowledge("josh")
        fact_id = facts[0]["id"]
        result = self.mm.delete_fact(fact_id)
        self.assertTrue(result)
        self.assertEqual(len(self.mm.recall_knowledge("josh")), 0)

    # ── Core Identity Tests ───────────────────────────────────────────────────

    def test_update_and_get_personality(self):
        result = self.mm.update_personality("test_trait", "test_value")
        self.assertTrue(result)
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("test_trait"), "test_value")

    def test_update_personality_conflict(self):
        self.mm.update_personality("test_trait", "old_value")
        result = self.mm.update_personality("test_trait", "new_value")
        self.assertTrue(result)
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("test_trait"), "new_value")

    def test_update_personality_strips_whitespace(self):
        result = self.mm.update_personality("  spaced_trait  ", "  spaced_value  ")
        self.assertTrue(result)
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("spaced_trait"), "spaced_value")

    def test_get_personality_details(self):
        self.mm.update_personality("humor", "high")
        details = self.mm.get_personality_details()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["trait_name"], "humor")
        self.assertEqual(details[0]["trait_value"], "high")

    def test_delete_personality(self):
        self.mm.update_personality("humor", "high")
        self.mm.delete_personality("humor")
        personality = self.mm.get_personality()
        self.assertNotIn("humor", personality)

    def test_personality_exceptions(self):
        with patch.object(self.mm, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.mm.update_personality("humor", "high"))
            self.assertEqual(self.mm.get_personality(), {})
            self.assertEqual(self.mm.get_personality_details(), [])
            self.assertFalse(self.mm.delete_personality("humor"))

    # ── Episodic Memory Tests ─────────────────────────────────────────────────

    def test_write_and_get_diary_entry(self):
        result = self.mm.write_diary_entry("Had a great day!", "session_1", 0.9)
        self.assertTrue(result)
        episodes = self.mm.get_recent_episodes()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["content"], "Had a great day!")
        self.assertEqual(episodes[0]["session_name"], "session_1")
        self.assertEqual(episodes[0]["sentiment_score"], 0.9)

    def test_delete_episode(self):
        self.mm.write_diary_entry("Had a great day!")
        episodes = self.mm.get_recent_episodes()
        episode_id = episodes[0]["id"]
        result = self.mm.delete_episode(episode_id)
        self.assertTrue(result)
        self.assertEqual(len(self.mm.get_recent_episodes()), 0)

    def test_episodic_memory_exceptions(self):
        with patch.object(self.mm, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.mm.write_diary_entry("Had a great day!"))
            self.assertEqual(self.mm.get_recent_episodes(), [])
            self.assertFalse(self.mm.delete_episode(1))

if __name__ == '__main__':
    unittest.main()
