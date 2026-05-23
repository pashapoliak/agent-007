import json
import hashlib
import re

with open('AGENTS.md', 'r', encoding='utf-8') as f:
    content = f.read()

raw_blocks = [b.strip() for b in content.split('\n\n') if b.strip()]

def is_junk(text):
    if len(text) < 20:
        return True
    if re.match(r'^[-*=_#.\s]+$', text):
        return True
    return False

blocks = [b for b in raw_blocks if not is_junk(b)]

blocks.sort(key=len)

def make_id(text):
    h = hashlib.md5(text.encode('utf-8')).hexdigest()[:12]
    return 'b_' + h

data = [{'id': make_id(text), 'text': text} for text in blocks]


with open('unread.js', 'w', encoding='utf-8') as f:
    f.write('var READ = [];')
    f.write('var DATA = ')
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write(';\n')

print(f'Created unread.js with {len(data)} blocks (sorted by text length)')
print('Junk blocks filtered:', len(raw_blocks) - len(blocks))