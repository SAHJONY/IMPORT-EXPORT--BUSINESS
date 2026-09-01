#!/usr/bin/env bash
set -euo pipefail

# Read-only Docker/OpenClaw forensic inventory for the authorized SAHJONY Hostinger VPS.
# It does not restart Docker, create containers, alter volumes, expose environment
# values, touch Meta, or modify the WhatsApp Linked Device session.

ROOT_PREFIX="${ROOT_PREFIX:-/}"
root="${ROOT_PREFIX%/}"; [[ -n "$root" ]] || root=/
STATE_DIR="${SAHJONY_DOCKER_FORENSICS_STATE_DIR:-/var/lib/sahjony-openclaw-forensics}"
REPORT="$STATE_DIR/docker-metadata-report.json"
TSV="$STATE_DIR/docker-container-candidates.tsv"

p(){ if [[ "$root" == / ]]; then printf '/%s' "${1#/}"; else printf '%s/%s' "$root" "${1#/}"; fi; }
log(){ printf '[openclaw-docker-forensics] %s\n' "$*"; }

[[ "$(id -u)" -eq 0 ]] || { echo RUN_AS_ROOT_REQUIRED=1 >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo PYTHON3_REQUIRED=1 >&2; exit 3; }
install -d -m 700 "$STATE_DIR"
: > "$TSV"

containers_root="$(p /var/lib/docker/containers)"
volumes_root="$(p /var/lib/docker/volumes)"

# Raw Docker config.v2.json may contain env values. Parse only selected non-secret
# structural fields and ENV VARIABLE NAMES; never print raw Env entries.
if [[ -d "$containers_root" ]]; then
  while IFS= read -r cfg; do
    [[ -f "$cfg" ]] || continue
    python3 - "$cfg" "$TSV" <<'PY'
import json,sys,os,re
cfg,out=sys.argv[1:]
try:
    data=json.load(open(cfg,encoding='utf-8',errors='replace'))
except Exception:
    raise SystemExit(0)
config=data.get('Config') or {}
labels=config.get('Labels') or {}
env=config.get('Env') or []
env_names=[]
for item in env:
    if isinstance(item,str) and '=' in item:
        env_names.append(item.split('=',1)[0])
name=(data.get('Name') or '').lstrip('/')
image=config.get('Image') or data.get('Image') or ''
cmd=config.get('Cmd') or []
entry=config.get('Entrypoint') or []
wd=config.get('WorkingDir') or ''
compose={k:labels.get(k) for k in [
 'com.docker.compose.project','com.docker.compose.service',
 'com.docker.compose.project.working_dir','com.docker.compose.project.config_files'
] if labels.get(k)}
text=' '.join([name,str(image),str(cmd),str(entry),str(wd),' '.join(map(str,compose.values())),' '.join(env_names)]).lower()
score=0; reasons=[]
if re.search(r'openclaw|open[-_ ]?claw',text): score+=60; reasons.append('openclaw_reference')
if 'whatsapp' in text or any(re.search(r'WHATSAPP|BAILEYS|SESSION|AUTH',x,re.I) for x in env_names): score+=20; reasons.append('whatsapp_session_signal')
if compose: score+=10; reasons.append('compose_labels')
if image: score+=5; reasons.append('image_present')
if wd: score+=5; reasons.append('working_dir_present')
score=min(score,100)
row={
 'score':score,'container_id':os.path.basename(os.path.dirname(cfg)),'name':name,
 'image':str(image),'working_dir':wd,'cmd':cmd,'entrypoint':entry,
 'compose':compose,'env_names':sorted(set(env_names)),'reasons':reasons,
 'config_path':cfg,
}
with open(out,'a',encoding='utf-8') as f:
    f.write(json.dumps(row,separators=(',',':'))+'\n')
PY
  done < <(find "$containers_root" -mindepth 2 -maxdepth 2 -type f -name config.v2.json -print 2>/dev/null || true)
fi

python3 - "$TSV" "$REPORT" "$volumes_root" <<'PY'
import json,sys,os
src,report,volroot=sys.argv[1:]
rows=[]
if os.path.exists(src):
    for line in open(src,encoding='utf-8',errors='replace'):
        try: rows.append(json.loads(line))
        except Exception: pass
cands=sorted([r for r in rows if r.get('score',0)>=60],key=lambda r:(-r.get('score',0),r.get('container_id','')))
volume_names=[]
if os.path.isdir(volroot):
    try:
        for n in sorted(os.listdir(volroot))[:1000]:
            if n == 'metadata.db': continue
            path=os.path.join(volroot,n)
            if os.path.isdir(path): volume_names.append(n)
    except Exception: pass
out={
 'raw_container_config_count':len(rows),
 'openclaw_candidate_count':len(cands),
 'openclaw_candidates':cands[:20],
 'docker_volume_name_count':len(volume_names),
 'docker_volume_names':volume_names[:200],
 'secrets_redacted':True,
 'mutated_runtime':False,
}
json.dump(out,open(report,'w'),indent=2,sort_keys=True)
print(json.dumps(out,indent=2,sort_keys=True))
print(f"OPENCLAW_DOCKER_METADATA_CANDIDATE_COUNT={len(cands)}")
if len(cands)==1:
    print('OPENCLAW_DOCKER_METADATA_DECISION=ONE_STRONG_HISTORICAL_CANDIDATE')
elif len(cands)>1:
    print('OPENCLAW_DOCKER_METADATA_DECISION=AMBIGUOUS_HISTORICAL_CANDIDATES')
else:
    print('OPENCLAW_DOCKER_METADATA_DECISION=NO_STRONG_HISTORICAL_CANDIDATE')
PY

echo "OPENCLAW_DOCKER_METADATA_REPORT=$REPORT"
echo OPENCLAW_DOCKER_METADATA_FORENSICS_COMPLETE=1
