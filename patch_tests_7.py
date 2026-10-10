import re
with open('tests/test_personal_intelligence.py', 'r') as f:
    text = f.read()

text = text.replace('res = asyncio.run(loop._execute_tool("get_user_profile", {}))', 'res = asyncio.run(loop.execute_turn("get_user_profile", {}))')

with open('tests/test_personal_intelligence.py', 'w') as f:
    f.write(text)
