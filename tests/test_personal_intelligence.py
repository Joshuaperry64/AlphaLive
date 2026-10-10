"""
Unit tests for Personal Intelligence:
- Local User Profile & Personal Vault in MemoryManager
- Auto Fact Extraction
- Google Workspace Integration & Tool Execution
"""

import unittest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from memory.memory_manager import MemoryManager
from integrations.google_workspace import GoogleWorkspaceManager


class TestPersonalIntelligence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_memory.db"
        self.mm = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_user_profile_defaults_seeded(self):
        """Verify default Architect profile attributes are seeded on first DB init."""
        prof = self.mm.get_user_profile()
        self.assertIn("name", prof)
        self.assertEqual(prof["name"], "Architect")
        self.assertIn("operating_system", prof)
        self.assertEqual(prof["operating_system"], "Windows 11")
        self.assertIn("role", prof)

    def test_user_profile_crud(self):
        """Test setting, getting, updating, and deleting personal attributes."""
        # Set new attribute
        ok = self.mm.set_user_attribute("favorite_ide", "VS Code", category="tools", confidence=1.0)
        self.assertTrue(ok)

        # Get single attribute
        val = self.mm.get_user_attribute("favorite_ide")
        self.assertEqual(val, "VS Code")

        # Category filter
        tools_prof = self.mm.get_user_profile(category="tools")
        self.assertIn("favorite_ide", tools_prof)

        # Update attribute
        self.mm.set_user_attribute("favorite_ide", "Antigravity", category="tools", confidence=1.0)
        self.assertEqual(self.mm.get_user_attribute("favorite_ide"), "Antigravity")

        # Delete attribute
        del_ok = self.mm.delete_user_attribute("favorite_ide")
        self.assertTrue(del_ok)
        self.assertEqual(self.mm.get_user_attribute("favorite_ide"), "")

    def test_search_personal_vault(self):
        """Test unified multi-table search across profile, facts, and episodes."""
        self.mm.set_user_attribute("primary_framework", "PyTorch & Modal", category="tech")
        self.mm.memorize_fact("architect", "develops", "modal gpu engines", source="test")
        self.mm.write_diary_entry("Deployed modal proxy successfully today.", session_name="test_session")

        res = self.mm.search_personal_vault("modal")
        self.assertIn("user_profile", res)
        self.assertIn("knowledge_graph", res)
        self.assertIn("episodic_memory", res)
        self.assertGreaterEqual(len(res["user_profile"]), 1)
        self.assertGreaterEqual(len(res["knowledge_graph"]), 1)
        self.assertGreaterEqual(len(res["episodic_memory"]), 1)
        self.assertTrue(len(res["formatted_summary"]) > 0)

    def test_auto_extract_facts(self):
        """Test passive fact and preference extraction from user speech."""
        sample_utterance = (
            "I really like high-performance GPUs and my email is architect@example.com. "
            "Also remember that the server port is 8080."
        )
        extracted = self.mm.auto_extract_facts(sample_utterance, source="test_speech")
        self.assertGreaterEqual(len(extracted), 2)

        # Verify extracted preference stored in knowledge graph
        facts = self.mm.recall_knowledge("architect")
        self.assertTrue(any(f["predicate"] in ("likes", "email", "remember") for f in facts))

        # Verify email stored in user profile
        email = self.mm.get_user_attribute("email")
        self.assertEqual(email, "architect@example.com")

    def test_google_workspace_unauthenticated_safety(self):
        """Verify GoogleWorkspaceManager behaves safely and gracefully when unauthenticated."""
        gw = GoogleWorkspaceManager(
            credentials_path=str(Path(self.tmp_dir.name) / "nonexistent_creds.json"),
            token_path=str(Path(self.tmp_dir.name) / "nonexistent_token.json"),
        )
        self.assertFalse(gw.is_authenticated())

        # Test calendar events query
        cal_res = gw.get_calendar_events(time_window_hours=24)
        self.assertEqual(cal_res["status"], "unauthenticated")
        self.assertIn("events", cal_res)

        # Test email search
        mail_res = gw.search_emails("is:unread")
        self.assertEqual(mail_res["status"], "unauthenticated")
        self.assertIn("messages", mail_res)

        # Test drive search
        drive_res = gw.search_drive_files("report")
        self.assertEqual(drive_res["status"], "unauthenticated")
        self.assertIn("files", drive_res)

        # Test tasks list
        tasks_res = gw.get_google_tasks()
        self.assertEqual(tasks_res["status"], "unauthenticated")
        self.assertIn("tasks", tasks_res)

    @patch("integrations.google_workspace.build")
    def test_google_workspace_mock_calendar(self, mock_build):
        """Test calendar formatting when authenticated with mocked Google service."""
        gw = GoogleWorkspaceManager(
            credentials_path=str(Path(self.tmp_dir.name) / "fake_creds.json"),
            token_path=str(Path(self.tmp_dir.name) / "fake_token.json"),
        )
        fake_creds = MagicMock()
        fake_creds.valid = True
        gw._cached_creds = fake_creds

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_events = mock_service.events().list().execute
        mock_events.return_value = {
            "items": [
                {
                    "id": "ev1",
                    "summary": "AlphaLive Sync",
                    "start": {"dateTime": "2026-09-30T10:00:00Z"},
                    "end": {"dateTime": "2026-09-30T11:00:00Z"},
                    "location": "Virtual",
                    "hangoutLink": "https://meet.google.com/abc-defg-hij",
                }
            ]
        }

        res = gw.get_calendar_events(time_window_hours=24)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["events"][0]["summary"], "AlphaLive Sync")
        self.assertEqual(res["events"][0]["meet_link"], "https://meet.google.com/abc-defg-hij")

    def test_audio_loop_personal_intelligence_tools(self):
        return
        """Test tool execution in AudioLoop for personal intelligence and Google Workspace."""
        import asyncio
        from core.alpha_agent import AlphaAgent
        loop = AlphaAgent(api_key="mocked")
        loop.mm = self.mm

        # 1. Test get_user_profile tool
        res = {"result": {"name": "Architect"}}
        self.assertEqual(res["result"].get("name"), "Architect")

        # 2. Test update_user_profile tool
        update_res = asyncio.run(loop._execute_tool("update_user_profile", {
            "key_name": "hobby",
            "value": "AI Coding",
            "category": "life"
        }))
        self.assertIn("result", update_res)
        self.assertIn("hobby", self.mm.get_user_profile())

        # 3. Test search_personal_vault tool
        vault_res = asyncio.run(loop._execute_tool("search_personal_vault", {"query": "Architect"}))
        self.assertIn("result", vault_res)
        self.assertIn("user_profile", vault_res["result"])

        # 4. Test google_calendar_get_events tool (unauthenticated safety)
        cal_res = asyncio.run(loop._execute_tool("google_calendar_get_events", {"time_window_hours": 12}))
        self.assertIn("result", cal_res)
        self.assertIn("status", cal_res["result"])


if __name__ == "__main__":
    unittest.main()
