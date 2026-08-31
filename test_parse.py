def parse_and_format(text):
    if '[You]:' in text:
        return f'<div align="left" style="margin-right:40px;"><div style="background-color:rgba(0,255,255,0.1); padding:10px; border-radius:5px;"><span style="color:#00ffff;"><b>[YOU]</b></span><br/>{text.split("[You]:")[-1]}</div></div>'
    return text

print(parse_and_format("[You]: hello there"))
