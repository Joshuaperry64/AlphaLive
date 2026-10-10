import re
with open('tests/test_personal_intelligence.py', 'r') as f:
    text = f.read()

# Replace core.alpha_core to core.alpha_agent
text = text.replace('aloop.controller =', 'aloop.controller =')
text = text.replace('res = await aloop._execute_turn(goal, is_desktop=False)', 'res = await aloop.execute_turn(goal)')

with open('tests/test_personal_intelligence.py', 'w') as f:
    f.write(text)
