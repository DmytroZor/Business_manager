import sys

filepath = r'c:\Users\Dima\PycharmProjects\Fish_Market_Bot\app\utils\formatters.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('def build_deliveries_text('):
        new_lines.append(line)
        new_lines.append('    _closed_statuses = {"delivered", "failed", "cancelled"}\n')
        new_lines.append('    deliveries = [d for d in deliveries if d.get("status") not in _closed_statuses]\n')
        continue
    new_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Done formatters.py!')

filepath_kbd = r'c:\Users\Dima\PycharmProjects\Fish_Market_Bot\app\keyboards\inline\catalog.py'
with open(filepath_kbd, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if '_closed_statuses = {"delivered", "failed"}' in line:
        new_lines.append(line.replace('{"delivered", "failed"}', '{"delivered", "failed", "cancelled"}'))
        continue
    new_lines.append(line)

with open(filepath_kbd, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Done catalog.py!')

