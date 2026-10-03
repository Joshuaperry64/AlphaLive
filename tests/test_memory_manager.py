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
        result = self.mm.memorize_fact("architect", "likes", "cyberpunk")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("architect")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['subject'], "architect")
        self.assertEqual(facts[0]['predicate'], "likes")
        self.assertEqual(facts[0]['object'], "cyberpunk")

    def test_memorize_fact_strips_and_lowercases(self):
        result = self.mm.memorize_fact("  ARCHITECT  ", " LiKeS ", " CyberPunk   ")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("architect")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['subject'], "architect")
        self.assertEqual(facts[0]['predicate'], "likes")
        self.assertEqual(facts[0]['object'], "cyberpunk")

    def test_memorize_fact_default_source(self):
        result = self.mm.memorize_fact("architect", "likes", "cyberpunk")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("architect")
        self.assertEqual(facts[0]['source'], "conversation")

    def test_memorize_fact_custom_source(self):
        result = self.mm.memorize_fact("architect", "likes", "cyberpunk", source="system_prompt")
        self.assertTrue(result)

        facts = self.mm.recall_knowledge("architect")
        self.assertEqual(facts[0]['source'], "system_prompt")

    @patch.object(MemoryManager, '_get_conn')
    def test_memorize_fact_exception_handling(self, mock_get_conn):
        mock_get_conn.side_effect = sqlite3.Error("Test DB Error")
        result = self.mm.memorize_fact("architect", "likes", "cyberpunk")
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
        self.mm.memorize_fact("architect", "likes", "pizza")
        self.mm.memorize_fact("alice", "likes", "sushi")
        facts = self.mm.get_all_facts()
        self.assertEqual(len(facts), 2)

    def test_search_knowledge(self):
        self.mm.memorize_fact("architect", "likes", "pizza")
        self.mm.memorize_fact("alice", "likes", "sushi")
        results = self.mm.search_knowledge("pizza")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["subject"], "architect")

    def test_delete_fact(self):
        self.mm.memorize_fact("architect", "likes", "pizza")
        facts = self.mm.recall_knowledge("architect")
        fact_id = facts[0]["id"]
        result = self.mm.delete_fact(fact_id)
        self.assertTrue(result)
        self.assertEqual(len(self.mm.recall_knowledge("architect")), 0)

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

    def test_update_personality_non_string_value(self):
        result = self.mm.update_personality("int_trait", 123)
        self.assertTrue(result)
        personality = self.mm.get_personality()
        self.assertEqual(personality.get("int_trait"), "123")

    def test_update_personality_executes_upsert(self):
        self.mm.update_personality("test_trait", "old_value")

        with patch('memory.memory_manager.sqlite3.connect') as mock_connect:
            mock_conn = mock_connect.return_value
            # We enforce dict-like row access, but since mm._get_conn uses contextmanager we mock the yield
            self.mm.update_personality("test_trait", "new_value")

            # The actual execution happens via conn.execute
            calls = mock_conn.execute.call_args_list
            self.assertTrue(len(calls) > 0, "Expected execute to be called")
            sql = calls[0][0][0]
            args = calls[0][0][1]
            self.assertIn("ON CONFLICT(trait_name) DO UPDATE SET", sql)
            self.assertEqual(args, ("test_trait", "new_value"))

    def test_update_personality_exception_handling(self):
        with patch.object(self.mm, '_get_conn', side_effect=sqlite3.Error("Test DB Error")):
            result = self.mm.update_personality("humor", "high")
            self.assertFalse(result)

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

    # ── User Profile & Personal Intelligence Tests ────────────────────────────

    def test_set_user_attribute(self):
        result = self.mm.set_user_attribute("favorite_color", "blue", category="preferences", confidence=0.9, source="chat")
        self.assertTrue(result)

        # Verify it was inserted correctly
        val = self.mm.get_user_attribute("favorite_color")
        self.assertEqual(val, "blue")

        # Test upsert behavior
        result_upsert = self.mm.set_user_attribute("favorite_color", "red")
        self.assertTrue(result_upsert)

        val_updated = self.mm.get_user_attribute("favorite_color")
        self.assertEqual(val_updated, "red")

    def test_set_user_attribute_strips_strings(self):
        result = self.mm.set_user_attribute("  spaced_key  ", "  spaced_val  ", category="  spaced_cat  ", source="  spaced_src  ")
        self.assertTrue(result)

        val = self.mm.get_user_attribute("spaced_key")
        self.assertEqual(val, "spaced_val")

        details = self.mm.get_user_profile_details()
        matching = [d for d in details if d["key_name"] == "spaced_key"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["category"], "spaced_cat")
        self.assertEqual(matching[0]["source"], "spaced_src")

    def test_get_user_attribute(self):
        self.mm.set_user_attribute("test_attr", "test_val")
        self.assertEqual(self.mm.get_user_attribute("test_attr"), "test_val")
        self.assertEqual(self.mm.get_user_attribute("nonexistent"), "")

    def test_get_user_profile(self):
        # Initial DB setup seeds some defaults. Let's clear them first for a clean test
        with self.mm._get_conn() as conn:
            conn.execute('DELETE FROM user_profile')
            conn.commit()

        self.mm.set_user_attribute("attr1", "val1", category="cat1")
        self.mm.set_user_attribute("attr2", "val2", category="cat1")
        self.mm.set_user_attribute("attr3", "val3", category="cat2")

        full_profile = self.mm.get_user_profile()
        self.assertEqual(len(full_profile), 3)
        self.assertEqual(full_profile["attr1"], "val1")

        cat1_profile = self.mm.get_user_profile("cat1")
        self.assertEqual(len(cat1_profile), 2)
        self.assertIn("attr1", cat1_profile)
        self.assertIn("attr2", cat1_profile)
        self.assertNotIn("attr3", cat1_profile)

    def test_get_user_profile_details(self):
        with self.mm._get_conn() as conn:
            conn.execute('DELETE FROM user_profile')
            conn.commit()

        self.mm.set_user_attribute("test_attr", "test_val", category="test_cat", confidence=0.8, source="test_src")
        details = self.mm.get_user_profile_details()

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["key_name"], "test_attr")
        self.assertEqual(details[0]["value"], "test_val")
        self.assertEqual(details[0]["category"], "test_cat")
        self.assertEqual(details[0]["confidence"], 0.8)
        self.assertEqual(details[0]["source"], "test_src")

    def test_delete_user_attribute(self):
        self.mm.set_user_attribute("attr_to_delete", "val")
        self.assertEqual(self.mm.get_user_attribute("attr_to_delete"), "val")

        result = self.mm.delete_user_attribute("attr_to_delete")
        self.assertTrue(result)
        self.assertEqual(self.mm.get_user_attribute("attr_to_delete"), "")

    def test_user_profile_exceptions(self):
        with patch.object(self.mm, '_get_conn', side_effect=Exception("Test error")):
            self.assertFalse(self.mm.set_user_attribute("key", "val"))
            self.assertEqual(self.mm.get_user_attribute("key"), "")
            self.assertEqual(self.mm.get_user_profile(), {})
            self.assertEqual(self.mm.get_user_profile_details(), [])
            self.assertFalse(self.mm.delete_user_attribute("key"))

    def test_search_personal_vault(self):
        # Seed some data
        self.mm.set_user_attribute("hobby", "playing guitar")
        self.mm.memorize_fact("architect", "owns", "acoustic guitar")
        self.mm.write_diary_entry("Practiced guitar for an hour today.", session_name="session_1")

        results = self.mm.search_personal_vault("guitar")

        self.assertEqual(results["query"], "guitar")
        self.assertEqual(len(results["user_profile"]), 1)
        self.assertEqual(results["user_profile"][0]["key_name"], "hobby")

        self.assertEqual(len(results["knowledge_graph"]), 1)
        self.assertEqual(results["knowledge_graph"][0]["object"], "acoustic guitar")

        self.assertEqual(len(results["episodic_memory"]), 1)
        self.assertEqual(results["episodic_memory"][0]["content"], "Practiced guitar for an hour today.")

        self.assertIn("hobby=playing guitar", results["formatted_summary"])
        self.assertIn("(architect owns acoustic guitar)", results["formatted_summary"])
        self.assertIn("[session_1] Practiced guitar for an hour today.", results["formatted_summary"])

    def test_search_personal_vault_exception(self):
        with patch.object(self.mm, '_get_conn', side_effect=Exception("Test error")):
            results = self.mm.search_personal_vault("guitar")
            self.assertEqual(results["query"], "guitar")
            self.assertEqual(results["user_profile"], [])
            self.assertEqual(results["knowledge_graph"], [])
            self.assertEqual(results["episodic_memory"], [])
            self.assertEqual(results["formatted_summary"], "")

    def test_auto_extract_facts(self):
        # Clear out existing defaults to avoid confusion
        with self.mm._get_conn() as conn:
            conn.execute('DELETE FROM user_profile')
            conn.execute('DELETE FROM knowledge_graph')
            conn.commit()

        text = "I really love cyberpunk aesthetics. I am working on a new project."
        extracted = self.mm.auto_extract_facts(text)

        self.assertEqual(len(extracted), 2)

        # Check the extracted list
        keys = [e["key"] for e in extracted]
        self.assertIn("preference", keys)
        self.assertIn("current_focus", keys)

        # Verify it went to DB
        prof = self.mm.get_user_profile()
        self.assertIn("preference", prof)
        self.assertEqual(prof["preference"], "cyberpunk aesthetics")
        self.assertIn("current_focus", prof)
        self.assertEqual(prof["current_focus"], "a new project")

        facts = self.mm.get_all_facts()
        self.assertEqual(len(facts), 2)
        predicates = [f["predicate"] for f in facts]
        self.assertIn("likes", predicates)
        self.assertIn("working_on", predicates)

    def test_auto_extract_facts_empty(self):
        extracted = self.mm.auto_extract_facts("Hi")
        self.assertEqual(extracted, [])

        extracted2 = self.mm.auto_extract_facts("")
        self.assertEqual(extracted2, [])

if __name__ == '__main__':
    unittest.main()
