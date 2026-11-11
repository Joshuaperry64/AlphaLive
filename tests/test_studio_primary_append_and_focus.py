import sys
import os
import gc
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.image_studio_manager import ImageStudioManager
from core.alpha_agent import AlphaAgent

class TestStudioPrimaryAppendAndFocus(unittest.TestCase):
    def setUp(self):
        self._orig_mock = os.getenv("ALPHALIVE_OFFLINE_MOCK")
        os.environ["ALPHALIVE_OFFLINE_MOCK"] = "1"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.ism = ImageStudioManager(db_path=self.db_path)

    def tearDown(self):
        del self.ism
        gc.collect()
        self.temp_dir.cleanup()
        if self._orig_mock is not None:
            os.environ["ALPHALIVE_OFFLINE_MOCK"] = self._orig_mock
        else:
            os.environ.pop("ALPHALIVE_OFFLINE_MOCK", None)

    def test_primary_append_prepending(self):
        """Verify PRIMARY APPEND prepends to AI prompts (e.g. 'realistic' + 'red car' -> 'realistic red car')."""
        self.ism.primary_append = "realistic"
        res = self.ism.generate_image(prompt="red car", model_name="jugg", steps=10)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["prompt"].startswith("realistic red car"))
        self.assertTrue(res["refined_prompt"].startswith("realistic red car"))

    def test_primary_append_no_duplicate(self):
        """Verify PRIMARY APPEND does not duplicate if prompt already begins with prefix."""
        self.ism.primary_append = "realistic"
        res = self.ism.generate_image(prompt="realistic red car", model_name="jugg", steps=10)
        self.assertEqual(res["status"], "success")
        self.assertFalse(res["prompt"].startswith("realistic realistic"))
        self.assertTrue(res["prompt"].startswith("realistic red car"))

    def test_set_primary_append_persistence(self):
        """Verify set_primary_append persists to config.json."""
        cfg_file = Path(self.temp_dir.name) / "config.json"
        ok = self.ism.set_primary_append("masterpiece, 8k", cfg_path=cfg_file)
        self.assertTrue(ok)
        self.assertEqual(self.ism.primary_append, "masterpiece, 8k")
        self.assertTrue(cfg_file.exists())
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("Studio", {}).get("PrimaryAppend"), "masterpiece, 8k")

        # Test loading it back into a new manager
        ism2 = ImageStudioManager(db_path=self.db_path)
        ism2._load_primary_append(cfg_path=cfg_file)
        self.assertEqual(ism2.primary_append, "masterpiece, 8k")

    def test_studio_mode_tool_restriction(self):
        """Verify studio_mode restricts agent tools strictly to media generation & core memory tools."""
        agent = AlphaAgent()
        agent.studio_manager = self.ism
        agent.studio_mode = False

        # Normal mode includes OS automation tools
        normal_tools = agent._get_tools()
        self.assertIsNotNone(normal_tools)
        normal_names = [d.name for d in normal_tools[0].function_declarations]
        self.assertIn("mouse_click", normal_names)
        self.assertIn("type_text", normal_names)
        self.assertIn("generate_image", normal_names)

        # In studio_mode, desktop mouse/typing tools must be stripped
        agent.studio_mode = True
        studio_tools = agent._get_tools()
        self.assertIsNotNone(studio_tools)
        studio_names = [d.name for d in studio_tools[0].function_declarations]
        self.assertNotIn("mouse_click", studio_names)
        self.assertNotIn("type_text", studio_names)
        self.assertNotIn("press_key", studio_names)
        self.assertNotIn("mouse_drag", studio_names)
        self.assertIn("generate_image", studio_names)
        self.assertIn("memorize_fact", studio_names)
        self.assertIn("recall_knowledge", studio_names)
        self.assertIn("task_complete", studio_names)

        # Also verify OpenAI tool declarations
        agent.studio_mode = False
        oai_normal = agent._get_openai_tools()
        oai_normal_names = [t["function"]["name"] for t in oai_normal]
        self.assertIn("mouse_click", oai_normal_names)

        agent.studio_mode = True
        oai_studio = agent._get_openai_tools()
        oai_studio_names = [t["function"]["name"] for t in oai_studio]
        self.assertNotIn("mouse_click", oai_studio_names)
        self.assertIn("generate_image", oai_studio_names)

    def test_latest_studio_image_resolution(self):
        """Verify _get_latest_studio_image resolves the newest generated artwork."""
        agent = AlphaAgent()
        agent.studio_manager = self.ism
        res = self.ism.generate_image(prompt="test artwork", model_name="jugg", steps=5)
        img_path = res["image_path"]

        resolved = agent._get_latest_studio_image()
        self.assertIsNotNone(resolved)
        self.assertTrue(os.path.exists(resolved))

    def test_evaluate_and_critique_malformation_retry(self):
        """Verify malformed image triggers defect detection, prompt modification without primary_append, and retry."""
        agent = AlphaAgent()
        agent.studio_manager = self.ism
        self.ism.primary_append = "photorealistic"

        # Initial render
        res1 = self.ism.generate_image(prompt="cybernetic entity with four arms", model_name="jugg", steps=5)
        img_path1 = res1["image_path"]
        gen_id1 = res1["id"]

        agent.voice = MagicMock()
        agent.client = MagicMock()

        # Step 1: Vision returns MALFORMED on first call, OK on second call
        mock_resp_malformed = MagicMock()
        mock_resp_malformed.text = (
            "STATUS: MALFORMED\n"
            "REASON: Extra mutated limb and distorted hand anatomy\n"
            "FIX: anatomically accurate hands, flawless limb symmetry"
        )

        mock_resp_ok = MagicMock()
        mock_resp_ok.text = (
            "STATUS: OK\n"
            "CRITIQUE: Striking cybernetic aesthetics with razor-sharp volumetric lighting and balanced metallic reflections."
        )

        agent.client.aio.models.generate_content = AsyncMock(side_effect=[mock_resp_malformed, mock_resp_ok])

        # Hook to verify GUI receives on_image_generated
        gui_updates = []
        agent.on_image_generated = lambda p, r: gui_updates.append((p, r))

        logs = []
        critique, final_path, final_id = asyncio.run(agent._evaluate_and_critique_image(
            img_path=img_path1,
            gen_id=gen_id1,
            prompt="cybernetic entity with four arms",
            model_name="jugg",
            retry_count=0,
            on_log=lambda m, c: logs.append(m)
        ))

        # Check results
        self.assertIn("Striking cybernetic aesthetics", critique)
        self.assertTrue(len(gui_updates) >= 2) # Both initial and retry images dispatched to GUI
        self.assertTrue(any("STUDIO DEFECT DETECTED" in l for l in logs))
        self.assertTrue(any("STUDIO RETRY PROMPT" in l for l in logs))

        # Verify announcement spoken aloud via TTS
        spoken_calls = [c[0][0] for c in agent.voice.queue_chunk.call_args_list]
        self.assertTrue(any("defective" in s.lower() for s in spoken_calls))
        self.assertTrue(any("striking cybernetic" in s.lower() for s in spoken_calls))

if __name__ == "__main__":
    unittest.main()
