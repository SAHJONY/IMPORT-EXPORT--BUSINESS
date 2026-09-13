#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib, json

src = Path('/var/lib/sahjony-crm-bridge/pending.jsonl')
if not src.exists() or not src.read_text(errors='ignore').strip():
    print('SOFIA_OUTREACH_QUARANTINE=EMPTY')
    raise SystemExit(0)

rows = []
for line in src.read_text(errors='ignore').splitlines():
    if not line.strip():
        continue
    item = json.loads(line)
    if not isinstance(item, dict):
        raise SystemExit('non_object_queue_row')
    rows.append(item)
if not rows:
    raise SystemExit(0)
if any(str(r.get('action') or '') != 'outreach-pilot' for r in rows):
    raise SystemExit('refusing_to_quarantine_mixed_queue')

times = [datetime.fromisoformat(str(r.get('queued_at') or '').replace('Z', '+00:00')) for r in rows]
now = datetime.now(timezone.utc)
if max(times) > now - timedelta(hours=24):
    raise SystemExit('refusing_to_quarantine_recent_outreach')

qdir = src.parent / 'quarantine'
qdir.mkdir(mode=0o700, exist_ok=True)
stamp = now.strftime('%Y%m%dT%H%M%SZ')
dst = qdir / f'pending-outreach-{stamp}.jsonl'
digest = hashlib.sha256(src.read_bytes()).hexdigest()
src.replace(dst)
dst.chmod(0o600)
manifest = qdir / f'pending-outreach-{stamp}.manifest.json'
manifest.write_text(json.dumps({
    'count': len(rows),
    'sha256': digest,
    'oldest': min(times).isoformat(),
    'newest': max(times).isoformat(),
    'reason': 'stale_outreach_fail_closed_quarantine',
}, separators=(',', ':')) + '\n')
manifest.chmod(0o600)
print('SOFIA_OUTREACH_QUARANTINED=' + str(len(rows)))
print('SOFIA_OUTREACH_QUARANTINE_SHA256=' + digest)
