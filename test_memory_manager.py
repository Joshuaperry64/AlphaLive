import unittest
import tempfile
import os
from memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        # We use a temporary file instead of ":memory:" because MemoryManager
        # opens a new connection for every query.
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.mm = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_recall_knowledge_returns_facts(self):
        self.mm.memorize_fact("test_subject", "is_a", "test")
        self.mm.memorize_fact("test_subject", "has", "value")
        self.mm.memorize_fact("other_subject", "is", "ignored")

        facts = self.mm.recall_knowledge("test_subject")
        self.assertEqual(len(facts), 2)

        # Verify the contents
        predicates = [f['predicate'] for f in facts]
        self.assertIn("is_a", predicates)
        self.assertIn("has", predicates)

        for fact in facts:
            self.assertEqual(fact['subject'], "test_subject")

    def test_recall_knowledge_empty_for_missing_subject(self):
        self.mm.memorize_fact("some_subject", "has", "value")
        facts = self.mm.recall_knowledge("nonexistent_subject")
        self.assertEqual(facts, [])

    def test_recall_knowledge_case_and_whitespace_insensitivity(self):
        # Insert using mixed case and spaces (memorize_fact normalizes to lower and strips)
        self.mm.memorize_fact("  Mixed Case Subject  ", "is", "test")

        # Query with different variations
        facts1 = self.mm.recall_knowledge("mixed case subject")
        facts2 = self.mm.recall_knowledge(" MIXED CASE SUBJECT ")
        facts3 = self.mm.recall_knowledge("MiXeD CaSe SuBjEcT")

        self.assertEqual(len(facts1), 1)
        self.assertEqual(facts1[0]['subject'], "mixed case subject")

        self.assertEqual(len(facts2), 1)
        self.assertEqual(facts2[0]['subject'], "mixed case subject")

        self.assertEqual(len(facts3), 1)
        self.assertEqual(facts3[0]['subject'], "mixed case subject")

    def test_recall_knowledge_handles_exceptions(self):
        self.mm.memorize_fact("test_subject", "is", "test")

        # Manually drop the table to force an exception in recall_knowledge
        with self.mm._get_conn() as conn:
            conn.execute("DROP TABLE knowledge_graph")
            conn.commit()

        # This should print an error but not raise, returning an empty list
        facts = self.mm.recall_knowledge("test_subject")
        self.assertEqual(facts, [])

if __name__ == "__main__":
    unittest.main()
