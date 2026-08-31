import sys
from PyQt6.QtWidgets import QApplication, QTextEdit
app = QApplication(sys.argv)
te = QTextEdit()
te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
html = '''
<div style="margin: 5px; padding: 10px; background-color: rgba(0,255,255,0.1); border: 1px solid rgba(0,255,255,0.3); border-radius: 5px; margin-right: 50px;">
<b style="color: #00ffff;">[YOU]</b><br/>Hello!
</div>
'''
te.insertHtml(html)
sys.exit(0)
