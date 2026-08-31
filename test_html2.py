import sys
from PyQt6.QtWidgets import QApplication, QTextEdit
app = QApplication(sys.argv)
te = QTextEdit()
te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

cur = te.textCursor()
# Start AI bubble
html = '''<div align="right" style="margin-left:50px;"><div style="background-color:rgba(255,0,255,0.1); border-radius:5px; padding:10px; color:#ff00ff; text-align:left;"><b>GEMINI</b><br/>'''
cur.insertHtml(html)

# Now insert plain text chunks as if streaming
cur.insertText("Hello ")
cur.insertText("there, ")
cur.insertText("how are you?\n")
cur.insertText("I am fine.")

# Close the div? QTextEdit auto-closes tags when you insertHtml, so insertText just appends outside the div? Let's see.
html2 = '''</div></div><br/>'''
cur.insertHtml(html2)

print(te.toHtml())
sys.exit(0)
