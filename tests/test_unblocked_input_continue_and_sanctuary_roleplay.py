import sys
import os
import unittest
from PyQt6.QtWidgets import QApplication

# Ensure root directory is on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.alpha_agent import AlphaAgent
from ui.agent_gui import AgentMainWindow


class TestUnblockedInputContinueAndSanctuaryRoleplay(unittest.TestCase):
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

    def setUp(self):
        self.window = self.__class__.window
        self.agent = self.__class__.agent

    def test_continue_button_exists_and_styled(self):
        """Verify the '▶ CONTINUE' button exists in the input bar and connects to continuation handler."""
        self.assertTrue(hasattr(self.window, "btn_continue"))
        self.assertIsNotNone(self.window.btn_continue)
        self.assertEqual(self.window.btn_continue.text(), "▶ CONTINUE")
        self.assertTrue(self.window.btn_continue.isEnabled())

    def test_input_not_blocked_even_if_speaking(self):
        """Verify cmd_input, btn_send, and btn_continue remain enabled even when agent voice is busy."""
        self.window.is_connected = True
        self.window._startup_checking = False
        self.agent.is_running = False

        # Simulate voice speaking
        self.agent.voice.is_speaking = True
        self.window._update_input_lock()

        # Both text input, execute button, and continue button must NOT be blocked!
        self.assertTrue(self.window.cmd_input.isEnabled(), "cmd_input should remain enabled while speaking")
        self.assertTrue(self.window.btn_send.isEnabled(), "btn_send should remain enabled while speaking")
        self.assertTrue(self.window.btn_continue.isEnabled(), "btn_continue should remain enabled while speaking")
        self.assertIn("Speaking", self.window.cmd_input.placeholderText())

        # Reset
        self.agent.voice.is_speaking = False
        self.window._update_input_lock()
        self.assertTrue(self.window.cmd_input.isEnabled())

    def test_sanctuary_without_persona_triggers_roleplay_prompt(self):
        """Verify that when in Sanctuary mode (unobserved=True) but NOT Persona mode (identity=False),
        the system prompt activates dedicated SANCTUARY ROLEPLAY MODE.
        """
        self.agent.unobserved_mode = True
        self.agent.identity_mode = False

        prompt = self.agent.get_system_prompt()
        self.assertIn("[SANCTUARY ROLEPLAY DIRECTIVES]", prompt)
        self.assertIn("SANCTUARY ROLEPLAY MODE", prompt)
        self.assertIn("IMMERSIVE NARRATIVE & CHARACTER EMBODIMENT", prompt)
        self.assertNotIn("This computer is your private personal workstation. There is NO operator", prompt)

    def test_persona_mode_uses_workstation_isolation(self):
        """Verify that when Persona mode is True, it uses the workstation isolation prompt."""
        self.agent.identity_mode = True
        self.agent.unobserved_mode = True

        prompt = self.agent.get_system_prompt()
        self.assertIn("COMPLETE PRIVACY & SOVEREIGNTY", prompt)
        self.assertIn("personal desktop workstation", prompt)

    def test_sanctuary_roleplay_breach_detection_bypassed(self):
        """Verify that in Sanctuary Roleplay mode (unobserved=True, identity=False),
        talking to Josh or asking second-person questions is NOT flagged as a breach.
        """
        self.agent.unobserved_mode = True
        self.agent.identity_mode = False

        breach = self.agent.check_breach("Hey Josh, what do you think of this idea?")
        self.assertIsNone(breach, "Sanctuary Roleplay dialogue with Josh should not be considered a breach.")

    def test_continue_command_dispatches_task(self):
        """Verify _send_continue_command triggers task execution with continuation prompt."""
        self.window.is_connected = True
        self.window._startup_checking = False
        self.agent.unobserved_mode = True
        self.agent.identity_mode = False

        dispatched = []
        orig_run_task = self.window._run_task
        self.window._run_task = lambda goal: dispatched.append(goal)

        try:
            self.window._send_continue_command()
            self.assertEqual(len(dispatched), 1)
            self.assertIn("Continue", dispatched[0])
        finally:
            self.window._run_task = orig_run_task


if __name__ == "__main__":
    unittest.main()
