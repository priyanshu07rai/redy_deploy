import re
with open('requirements.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

clean_lines = []
for line in lines:
    line = line.strip()
    if not line: continue
    if '@ file://' in line:
        pkg = line.split('@')[0].strip()
        clean_lines.append(pkg)
    else:
        clean_lines.append(line)

if 'gunicorn' not in clean_lines:
    clean_lines.append('gunicorn')

with open('requirements.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(clean_lines))
