import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google.genai import types


class TestModalProxyProtocol(unittest.TestCase):
    def test_live_server_tool_call_extraction(self):
        """Verify that LiveServerMessage tool_call structure has function_calls and can be extracted."""
        # Create a mock LiveServerMessage with tool_call
        fc1 = types.FunctionCall(
            name="mouse_click",
            id="call_click_123",
            args={"x": 500, "y": 300, "button": "left", "clicks": 1}
        )
        fc2 = types.FunctionCall(
            name="type_text",
            id="call_type_456",
            args={"text": "hello world", "enter": True}
        )
        tc = types.LiveServerToolCall(function_calls=[fc1, fc2])
        msg = types.LiveServerMessage(tool_call=tc)

        self.assertIsNotNone(msg.tool_call)
        self.assertEqual(len(msg.tool_call.function_calls), 2)
        self.assertEqual(msg.tool_call.function_calls[0].name, "mouse_click")
        self.assertEqual(msg.tool_call.function_calls[0].args["x"], 500)
        self.assertEqual(msg.tool_call.function_calls[1].name, "type_text")

    def test_function_response_construction(self):
        """Verify that FunctionResponse constructs properly for tool responses."""
        resp1 = types.FunctionResponse(
            name="mouse_click",
            id="call_click_123",
            response={"result": "Clicked (500, 300)"}
        )
        self.assertEqual(resp1.name, "mouse_click")
        self.assertEqual(resp1.id, "call_click_123")
        self.assertEqual(resp1.response["result"], "Clicked (500, 300)")

        # Verify None id is supported
        resp2 = types.FunctionResponse(
            name="mouse_click",
            id=None,
            response={"result": "Clicked current"}
        )
        self.assertEqual(resp2.name, "mouse_click")
        self.assertIsNone(resp2.id)

    def test_live_connect_config_validation_with_tools(self):
        """Verify LiveConnectConfig validates tools properly from json payload."""
        tool_decl = {
            "functionDeclarations": [
                {
                    "name": "mouse_click",
                    "description": "Click the mouse at coordinates",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "x": {"type": "INTEGER", "description": "X coordinate"},
                            "y": {"type": "INTEGER", "description": "Y coordinate"}
                        }
                    }
                }
            ]
        }
        cfg_dict = {
            "responseModalities": ["AUDIO"],
            "tools": [tool_decl]
        }
        config = types.LiveConnectConfig.model_validate(cfg_dict)
        self.assertIsNotNone(config.tools)
        self.assertEqual(len(config.tools), 1)


if __name__ == "__main__":
    unittest.main()
