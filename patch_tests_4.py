with open('tests/test_personal_intelligence.py', 'r') as f:
    text = f.read()

# Replace core.alpha_core which no longer exists to core.alpha_agent
text = text.replace('from core.alpha_core import AudioLoop', 'from core.alpha_agent import AlphaAgent')
text = text.replace('aloop = AudioLoop(api_key="mocked")', 'aloop = AlphaAgent(api_key="mocked")')

with open('tests/test_personal_intelligence.py', 'w') as f:
    f.write(text)
