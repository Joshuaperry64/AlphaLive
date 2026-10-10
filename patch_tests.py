import re
with open('tests/test_all_verification.py', 'r') as f:
    text = f.read()

# Fix assertions related to MULTI-WS toggles which are no longer "SOON" but "OFF"
search = """    assert "SOON" in win.btn_t_workspace.text()
    assert not win.btn_t_workspace.isEnabled()"""
replace = """    assert "OFF" in win.btn_t_workspace.text()
    assert win.btn_t_workspace.isEnabled()"""
text = text.replace(search, replace)

with open('tests/test_all_verification.py', 'w') as f:
    f.write(text)
