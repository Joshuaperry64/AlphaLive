lines = open("main3.py", encoding="utf-8").readlines()
for i, l in enumerate(lines, 1):
    s = l.strip()
    if '""")' in s and i > 300 and i < 480:
        print(i, repr(l[:80]))
