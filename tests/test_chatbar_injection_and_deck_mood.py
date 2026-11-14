import sys
import os
import unittest
from PyQt6.QtWidgets import QApplication

# Ensure root directory is on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ui.agent_gui import AgentMainWindow


class TestChatbarInjectionAndDeckMood(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.window = AgentMainWindow()
        cls.agent = cls.window.agent

    @classmethod
    def tearDownClass(cls):
        try:
            cls.window.close()
        except Exception:
            pass

    def test_overseer_panel_retired(self):
        """Verify the floating covert control panel overlay is completely retired."""
        self.assertIsNone(getattr(self.window, "overseer_panel", None))
        self.window._sync_overseer_panel_visibility()
        self.assertIsNone(getattr(self.window, "overseer_panel", None))

    def test_chatbar_mode_toggle_and_dispatch(self):
        """Verify the chatbar mode switches between PROMPT and INJECTION and dispatches accordingly."""
        self.window.is_connected = True
        self.window._startup_checking = False
        self.agent.is_running = False

        # Ensure starting in PROMPT mode
        if self.window.is_thought_input_mode:
            self.window._toggle_input_mode()
        self.assertEqual(self.window.btn_input_mode.text(), "💬 PROMPT")
        self.assertEqual(self.window.btn_send.text(), "EXECUTE")

        dispatched = []
        orig_run_task = self.window._run_task
        self.window._run_task = lambda goal: dispatched.append(goal)

        try:
            # 1. Send as PROMPT
            self.window.cmd_input.setText("list open windows")
            self.window._send_text_command()
            self.assertEqual(len(dispatched), 1)
            self.assertEqual(dispatched[-1], "list open windows")

            # 2. Switch to INJECTION
            self.window._toggle_input_mode()
            self.assertTrue(self.window.is_thought_input_mode)
            self.assertEqual(self.window.btn_input_mode.text(), "⚡ INJECTION")
            self.assertEqual(self.window.btn_send.text(), "INJECT")
            self.assertIn("Inject subconscious impulse", self.window.cmd_input.placeholderText())

            # 3. Send as INJECTION
            self.window.cmd_input.setText("I should check Hacker News")
            self.window._send_text_command()
            self.assertEqual(len(dispatched), 2)
            self.assertEqual(dispatched[-1], "(A fleeting thought occurs to me: I should check Hacker News)")

            # 4. Continue in INJECTION mode
            self.window._send_continue_command()
            self.assertEqual(len(dispatched), 3)
            self.assertIn("internal train of thought continues", dispatched[-1])

            # 5. Switch back to PROMPT
            self.window._toggle_input_mode()
            self.assertFalse(self.window.is_thought_input_mode)
            self.assertEqual(self.window.btn_input_mode.text(), "💬 PROMPT")
            self.assertEqual(self.window.btn_send.text(), "EXECUTE")
        finally:
            self.window._run_task = orig_run_task

    def test_top_deck_mood_selector_and_sync(self):
        """Verify the Top Command Deck mood selector updates active mood, persists, and syncs."""
        self.assertTrue(hasattr(self.window, "deck_combo_mood"))

        # Switch to tactical
        idx_t = self.window.deck_combo_mood.findData("tactical")
        self.window.deck_combo_mood.setCurrentIndex(idx_t)
        self.assertEqual(self.agent.current_mood, "tactical")
        self.assertEqual(self.window.combo_mood.currentData(), "tactical")

        # Switch to sassy
        idx_s = self.window.deck_combo_mood.findData("sassy")
        self.window.deck_combo_mood.setCurrentIndex(idx_s)
        self.assertEqual(self.agent.current_mood, "sassy")
        self.assertEqual(self.window.combo_mood.currentData(), "sassy")

    def test_mood_alone_mode_guard(self):
        """Verify that selecting Luci requires Alone Mode, and disengaging Alone Mode reverts Luci."""
        # When Alone Mode is OFF, selecting luci is blocked and reverts
        self.agent.alone_mode = False
        self.agent.set_mood("default")

        idx_l = self.window.deck_combo_mood.findData("luci")
        self.window.deck_combo_mood.setCurrentIndex(idx_l)
        self.assertNotEqual(self.agent.current_mood, "luci")

        # Turn Alone Mode ON -> luci is allowed
        self.window._on_alone_mode_toggled(True)
        self.window.deck_combo_mood.setCurrentIndex(idx_l)
        self.assertEqual(self.agent.current_mood, "luci")

        # Turn Alone Mode OFF -> automatically reverts back to default
        self.window._on_alone_mode_toggled(False)
        self.assertEqual(self.agent.current_mood, "default")
        self.assertEqual(self.window.deck_combo_mood.currentData(), "default")


if __name__ == "__main__":
    unittest.main()
