import sys
import os
import gc
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.image_studio_manager import ImageStudioManager, MODEL_CATALOG, LORA_CATALOG, UPSCALER_CATALOG

class TestImageStudio(unittest.TestCase):
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

    def test_catalogs(self):
        self.assertIn("jugg", MODEL_CATALOG)
        self.assertIn("cyber", MODEL_CATALOG)
        self.assertIn("none", LORA_CATALOG)
        self.assertIn("realesrgan-x4plus", UPSCALER_CATALOG)

    def test_refine_prompt(self):
        base = "A portrait of a cyberpunk girl in rain"
        refined_p, refined_neg = self.ism.refine_prompt(base, "cyber")
        self.assertIn("portrait", refined_p.lower())
        self.assertIn("low quality", refined_neg.lower())

    def test_generate_and_upscale(self):
        # Generate procedural test image
        res = self.ism.generate_image(
            prompt="Cybernetic terminal HUD interface",
            model_name="jugg",
            steps=15,
            guidance=7.0,
            seed=42
        )
        self.assertIn("image_path", res)
        self.assertTrue(os.path.exists(res["image_path"]))
        gen_id = res["id"]

        # Upscale 4x
        up_res = self.ism.upscale_image(
            image_path=res["image_path"],
            scale=4,
            model_name="realesrgan-x4plus",
            generation_id=gen_id
        )
        self.assertTrue(up_res.get("success"))
        self.assertTrue(os.path.exists(up_res["upscaled_path"]))
        self.assertIn("4096", up_res["dimensions"])

        # Test feedback
        success = self.ism.record_feedback(
            generation_id=gen_id,
            rating=1,
            feedback_tags="lighting, style",
            user_feedback="Stunning neon reflections and sharpness"
        )
        self.assertTrue(success)

if __name__ == "__main__":
    unittest.main()
