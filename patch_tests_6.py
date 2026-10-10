import re
with open('tests/test_personal_intelligence.py', 'r') as f:
    text = f.read()

text = text.replace('loop = AudioLoop(video_mode="none")', 'loop = AlphaAgent(api_key="mocked")')

with open('tests/test_personal_intelligence.py', 'w') as f:
    f.write(text)
