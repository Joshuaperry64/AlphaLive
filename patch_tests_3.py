with open('tests/test_gui.py', 'r') as f:
    text = f.read()

text = text.replace('from ui import gui', 'from ui import agent_gui as gui')

with open('tests/test_gui.py', 'w') as f:
    f.write(text)
