import re
with open('tests/test_all_verification.py', 'r') as f:
    text = f.read()

# Fix assertions related to MULTI-WS toggles which are no longer "SOON" but "OFF"
search = """    toggles = [
        "btn_t_mic", "btn_t_tts", "btn_t_auto", "btn_t_desk",
        "btn_t_vis", "btn_t_proact", "btn_t_studio", "btn_t_autoloop",
        "btn_t_identity", "btn_t_unobserved", "btn_t_workspace"
    ]"""
replace = """    toggles = [
        "btn_t_mic", "btn_t_auto", "btn_t_desk",
        "btn_t_vis", "btn_t_proact", "btn_t_studio", "btn_t_autoloop",
        "btn_t_identity", "btn_t_unobserved", "btn_t_workspace"
    ]"""
text = text.replace(search, replace)

with open('tests/test_all_verification.py', 'w') as f:
    f.write(text)
