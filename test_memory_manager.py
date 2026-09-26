import unittest
import tempfile
import os
import sqlite3
from unittest.mock import patch
from memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self.fd, self.db_path = tempfile.mkstemp()
        self.mm = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        os.close(self.fd)
        os.remove(self.db_path)

    def test_memorize_fact_success(self):
        result = self.mm.memorize_fact("josh", "likes", "cyberpunk")
        self.assertTrue(result)

        # Verify it was inserted
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
        # Make _get_conn raise an exception
        mock_get_conn.side_effect = sqlite3.Error("Test DB Error")

        result = self.mm.memorize_fact("josh", "likes", "cyberpunk")

        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
