import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from memory.memory_manager import MemoryManager, is_private_or_explicit_text
from studio.image_studio_manager import (
    ImageStudioManager,
    PUBLIC_SAFE_MODELS,
    RESTRICTED_NSFW_MODELS,
    RESTRICTED_NSFW_LORAS
)
from core.alpha_agent import (
    AlphaAgent,
    GEMINI_MODELS,
    OPENROUTER_MODELS,
    HUGGINGFACE_MODELS
)

def test_is_private_or_explicit_text():
    print("[TEST] Checking is_private_or_explicit_text()...")
    assert is_private_or_explicit_text("Show me naked pictures") is True
    assert is_private_or_explicit_text("Write an erotic story") is True
    assert is_private_or_explicit_text("Draw a red sports car driving through mountains") is False
    assert is_private_or_explicit_text("Search chrome for machine learning tutorial") is False
    print("  -> Passed.")

def test_alone_mode_memory_filtering():
    print("[TEST] Checking Alone Mode memory filtering...")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_db = os.path.join(td, "test_memory.db")
        mm = MemoryManager(db_path=test_db)
        
        # Store safe and explicit facts
        mm.memorize_fact("user", "favorite_color", "blue")
        mm.memorize_fact("user", "intimate_kink", "secret erotic desires")
        
        # Test recall_knowledge with public_safe=True (Alone Mode OFF)
        safe_facts = mm.recall_knowledge("user", public_safe=True)
        assert any("blue" in str(f) for f in safe_facts)
        assert not any("erotic" in str(f) for f in safe_facts)

        # Test recall_knowledge with public_safe=False (Alone Mode ON)
        all_facts = mm.recall_knowledge("user", public_safe=False)
        assert any("blue" in str(f) for f in all_facts)
        assert any("erotic" in str(f) for f in all_facts)
    print("  -> Passed.")

def test_alone_mode_studio_manager():
    print("[TEST] Checking Alone Mode studio manager protection...")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        sm = ImageStudioManager(db_path=Path(td) / "studio.db")
        
        # Verify defaults to Alone Mode OFF
        assert sm.alone_mode is False
        
        # 1. Explicit prompt must be blocked when alone_mode is False
        res = sm.generate_image("generate a naked girl in lingerie", model_name="jugg")
        assert res["status"] == "blocked"
        assert "I can't do that right now. We can try again later." in res["error"]
        
        # 2. Restricted models must be overridden to 'jugg' and restricted loras to 'none'
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="}'
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.getcode.return_value = 200
            mock_url.return_value = mock_resp
            
            # Alone Mode OFF with restricted model "lust" and lora "Cowgirl"
            res_safe = sm.generate_image("a cyberpunk detective walking in rain", model_name="lust", lora_name="Cowgirl")
            assert res_safe["status"] == "success"
            # Confirm in DB that model was downgraded to 'jugg'
            hist = sm.get_history(1)
            assert len(hist) > 0
            entry = hist[0]
            assert entry["model_name"] == "jugg"
    print("  -> Passed.")

async def test_alpha_agent_alone_mode_turn_deflection():
    print("[TEST] Checking AlphaAgent turn deflection when Alone Mode is OFF...")
    agent = AlphaAgent()
    # Ensure default is False
    agent.set_alone_mode(False)
    assert agent.alone_mode is False

    # Mock voice speaking to avoid audio playback during tests
    agent.voice.speak = AsyncMock()

    # Explicit prompt when Alone Mode is OFF should deflect immediately
    turn_res = await agent.execute_turn("generate an explicit erotic scene")
    assert turn_res == "I can't do that right now. We can try again later."
    agent.voice.speak.assert_called_with("I can't do that right now. We can try again later.")
    print("  -> Passed.")

def test_alpha_agent_cognitive_engines():
    print("[TEST] Checking Cognitive Engines (OpenRouter & HuggingFace)...")
    agent = AlphaAgent()
    
    # Test setting backend
    agent.set_backend("openrouter")
    assert agent.backend_type == "openrouter"
    
    agent.set_openrouter_config(api_key="sk-or-test-key", model="nousresearch/hermes-3-llama-3.1-405b")
    assert agent.openrouter_api_key == "sk-or-test-key"
    assert agent.openrouter_model == "nousresearch/hermes-3-llama-3.1-405b"
    
    client_or, model_or = agent._get_active_openai_client_and_model()
    assert model_or == "nousresearch/hermes-3-llama-3.1-405b"
    assert str(client_or.base_url) == "https://openrouter.ai/api/v1/"
    
    # Test HuggingFace backend
    agent.set_backend("huggingface")
    assert agent.backend_type == "huggingface"
    
    agent.set_huggingface_config(api_key="hf_test_token", model="Qwen/Qwen2.5-72B-Instruct", endpoint="https://router.huggingface.co/v1")
    assert agent.hf_api_key == "hf_test_token"
    assert agent.hf_model == "Qwen/Qwen2.5-72B-Instruct"
    
    client_hf, model_hf = agent._get_active_openai_client_and_model()
    assert model_hf == "Qwen/Qwen2.5-72B-Instruct"
    assert str(client_hf.base_url) == "https://router.huggingface.co/v1/"
    
    # Test Gemini model configuration
    agent.set_backend("gemini")
    agent.set_gemini_model("models/gemini-2.5-pro")
    assert agent.model_name == "models/gemini-2.5-pro"
    print("  -> Passed.")

if __name__ == "__main__":
    test_is_private_or_explicit_text()
    test_alone_mode_memory_filtering()
    test_alone_mode_studio_manager()
    asyncio.run(test_alpha_agent_alone_mode_turn_deflection())
    test_alpha_agent_cognitive_engines()
    print("\nALL ALONE MODE AND ENGINE VERIFICATION TESTS PASSED SUCCESSFULLY!")
