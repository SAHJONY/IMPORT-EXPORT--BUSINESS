#!/usr/bin/env bash
set -euo pipefail

# Read-only OpenClaw runtime provenance correlator.
# It never prints env values, never mutates Docker/WhatsApp state, and never
# chooses a reconstruction target from a .env file alone.

STATE_DIR="${SAHJONY_OPENCLAW_CORRELATOR_STATE_DIR:-/var/lib/sahjony-openclaw-correlator}"
REPORT="$STATE_DIR/report.json"
DECISION="$STATE_DIR/decision.json"
MIN_SCORE="${SAHJONY_OPENCLAW_CORRELATOR_MIN_SCORE:-90}"

log(){ printf '[openclaw-runtime-correlator] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger VPS'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
[[ "$MIN_SCORE" =~ ^[0-9]+$ ]] || fail 'SAHJONY_OPENCLAW_CORRELATOR_MIN_SCORE must be numeric'
install -d -m 700 "$STATE_DIR"

python3 - "$REPORT" "$DECISION" "$MIN_SCORE" <<'PY'
import json, os, re, sys, time
from pathlib import Path

report_path, decision_path, min_score_s = sys.argv[1:]
min_score = int(min_score_s)
SEARCH_ROOTS = ['/root', '/opt', '/srv', '/etc', '/usr/local']
COMPOSE_NAMES = {'docker-compose.yml','docker-compose.yaml','compose.yml','compose.yaml'}
MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 700
MAX_WALK = 5000


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return ''
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def walk_count(path, limit=MAX_WALK):
    count = 0
    try:
        for _base, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'.git','node_modules','__pycache__'}]
            count += len(files)
            if count >= limit:
                return limit
    except OSError:
        pass
    return count


def collect_named(names=None, name_rx=None, max_depth=9):
    out, seen = [], set()
    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        root_depth = root.rstrip('/').count('/')
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            depth = base.count('/') - root_depth
            if depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d not in {'.git','node_modules','__pycache__'}]
            for name in files:
                if names is not None and name not in names:
                    continue
                if name_rx is not None and not re.search(name_rx, name, re.I):
                    continue
                p = os.path.join(base, name)
                if p in seen:
                    continue
                seen.add(p); out.append(p)
                if len(out) >= MAX_FILES:
                    return sorted(out)
    return sorted(out)


def safe_mtime(path):
    try: return int(os.path.getmtime(path))
    except OSError: return 0


def path_refs(text):
    # Extract structural filesystem references only. Never return assignments or values.
    refs = set()
    for m in re.finditer(r'(?<![A-Za-z0-9_])(/(?:root|opt|srv|etc|var|usr)/[A-Za-z0-9._/@+\-]+(?:/[A-Za-z0-9._/@+\-]+)*)', text):
        refs.add(m.group(1).rstrip('.,;:'))
    return refs


def compose_refs(text, source_dir):
    refs = set()
    for token in re.findall(r'[^\s\'\";]+(?:docker-compose|compose)\.ya?ml', text, re.I):
        token = token.strip('()[]{}<>`')
        if token.startswith('/'):
            refs.add(os.path.normpath(token))
        else:
            refs.add(os.path.normpath(os.path.join(source_dir, token)))
    return refs


def deployment_evidence():
    refs, dirs, script_meta = set(), set(), []
    scripts = collect_named(name_rx=r'(openclaw|claw).*(\.sh|\.service)$|^openclaw-deploy\.sh$')
    for p in scripts:
        text = read_text(p)
        if not re.search(r'openclaw|open[ _-]?claw|claw gateway|whatsapp', text, re.I):
            continue
        local_refs = compose_refs(text, os.path.dirname(p))
        refs.update(local_refs)
        for r in path_refs(text):
            if os.path.isdir(r): dirs.add(os.path.realpath(r))
        script_meta.append({
            'path': p, 'mtime': safe_mtime(p),
            'compose_refs': sorted(local_refs),
            'mentions_docker': bool(re.search(r'\bdocker\b|docker[ -]?compose', text, re.I)),
            'mentions_openclaw': True,
            'mentions_whatsapp': bool(re.search(r'whatsapp|baileys|linked.?device', text, re.I)),
        })
    return refs, dirs, sorted(script_meta, key=lambda x:(-x['mtime'],x['path']))


def history_evidence():
    refs, dirs, meta = set(), set(), []
    for p in ['/root/.bash_history','/root/.zsh_history']:
        text = read_text(p)
        if not text: continue
        hit_count = 0
        for line in text.splitlines()[-4000:]:
            if not re.search(r'openclaw|open[ _-]?claw|whatsapp|docker\s+(?:compose|run|start|create)', line, re.I):
                continue
            hit_count += 1
            refs.update(compose_refs(line, '/root'))
            m = re.search(r'(?:^|[;&]\s*|\s)cd\s+([^\s;&]+)', line)
            if m:
                d = m.group(1).strip('"\'')
                if d.startswith('/') and os.path.isdir(d): dirs.add(os.path.realpath(d))
        meta.append({'path':p,'structural_hit_count':hit_count,'mtime':safe_mtime(p)})
    return refs, dirs, meta


def raw_docker_evidence():
    rows, compose_refs_found, working_dirs = [], set(), set()
    root='/var/lib/docker/containers'
    if not os.path.isdir(root):
        return rows, compose_refs_found, working_dirs
    for cfg in Path(root).glob('*/config.v2.json'):
        try:
            data=json.loads(cfg.read_text(encoding='utf-8',errors='replace'))
        except Exception:
            continue
        conf=data.get('Config') or {}; labels=conf.get('Labels') or {}; env=conf.get('Env') or []
        env_names=sorted({x.split('=',1)[0] for x in env if isinstance(x,str) and '=' in x})
        name=(data.get('Name') or '').lstrip('/'); image=str(conf.get('Image') or data.get('Image') or '')
        wd=str(conf.get('WorkingDir') or '')
        project_wd=str(labels.get('com.docker.compose.project.working_dir') or '')
        cfgs=str(labels.get('com.docker.compose.project.config_files') or '')
        service=str(labels.get('com.docker.compose.service') or '')
        project=str(labels.get('com.docker.compose.project') or '')
        text=' '.join([name,image,wd,project_wd,cfgs,service,project,' '.join(env_names)]).lower()
        openclaw_signal=bool(re.search(r'openclaw|open[-_ ]?claw|claw',text))
        whatsapp_signal=('whatsapp' in text or any(re.search(r'WHATSAPP|BAILEYS|SESSION|AUTH',n,re.I) for n in env_names))
        if not (openclaw_signal or whatsapp_signal):
            continue
        if project_wd and os.path.isdir(project_wd): working_dirs.add(os.path.realpath(project_wd))
        for item in re.split(r'[,;]',cfgs):
            item=item.strip()
            if not item: continue
            if item.startswith('/'): compose_refs_found.add(os.path.normpath(item))
            elif project_wd: compose_refs_found.add(os.path.normpath(os.path.join(project_wd,item)))
        rows.append({
            'container_id':cfg.parent.name,'name':name,'image':image,'working_dir':wd,
            'compose_project':project,'compose_service':service,'compose_working_dir':project_wd,
            'compose_config_files':sorted([x for x in compose_refs_found if project_wd and x.startswith(os.path.normpath(project_wd)+os.sep)]),
            'env_names':env_names,'openclaw_signal':openclaw_signal,'whatsapp_signal':whatsapp_signal,
            'mtime':safe_mtime(str(cfg)),
        })
    return sorted(rows,key=lambda x:(-x['mtime'],x['container_id'])), compose_refs_found, working_dirs


def systemd_evidence():
    refs, dirs, units=[] , set(), []
    for root in ['/etc/systemd/system','/usr/lib/systemd/system','/lib/systemd/system']:
        if not os.path.isdir(root): continue
        for p in Path(root).glob('**/*'):
            if not p.is_file(): continue
            text=read_text(str(p))
            if not re.search(r'openclaw|open[ _-]?claw|whatsapp|claw gateway',text,re.I): continue
            local=compose_refs(text,str(p.parent)); refs.update(local)
            m=re.search(r'^WorkingDirectory=(.+)$',text,re.M)
            if m:
                d=m.group(1).strip()
                if d.startswith('/') and os.path.isdir(d): dirs.add(os.path.realpath(d))
            units.append({'path':str(p),'compose_refs':sorted(local),'mtime':safe_mtime(str(p))})
            if len(units)>=100: break
    return refs,dirs,units


def session_state_near(base):
    roots=[base,os.path.dirname(base)]
    hits=[]
    rx=re.compile(r'(whatsapp|baileys|creds\.json|session|linked.?device|auth)',re.I)
    for root in roots:
        if not os.path.isdir(root): continue
        n=0
        for b,dirs,files in os.walk(root,topdown=True,followlinks=False):
            rel=os.path.relpath(b,root)
            depth=0 if rel=='.' else rel.count(os.sep)+1
            if depth>=4: dirs[:]=[]
            dirs[:]=[d for d in dirs if d not in {'.git','node_modules','__pycache__','state-snapshots'}]
            for f in files:
                if rx.search(f):
                    p=os.path.join(b,f)
                    try: size=os.path.getsize(p)
                    except OSError: size=0
                    if size>0: hits.append({'path':p,'size':size,'mtime':safe_mtime(p)})
                    n+=1
                    if n>=40: break
            if n>=40: break
    unique={x['path']:x for x in hits}
    return sorted(unique.values(),key=lambda x:(-x['mtime'],x['path']))[:40]


def parse_bind_sources(text, compose_dir):
    sources=set()
    for m in re.finditer(r'(?m)^\s*-\s*([^\s:#][^:#]*):[^\n#]+$',text):
        raw=m.group(1).strip().strip('"\'')
        if '${' in raw: continue
        if raw.startswith('/'):
            src=os.path.normpath(raw)
        elif raw.startswith('./') or raw.startswith('../'):
            src=os.path.normpath(os.path.join(compose_dir,raw))
        else:
            continue
        if src.startswith('/var/lib/docker'): continue
        if os.path.exists(src): sources.add(src)
    return sorted(sources)


def named_volume_state(text):
    names=set()
    # Conservative: only simple volume source tokens from service mount lines.
    for m in re.finditer(r'(?m)^\s*-\s*([A-Za-z0-9_.-]+):/[^\n#]+$',text): names.add(m.group(1))
    hits=[]
    vroot='/var/lib/docker/volumes'
    if os.path.isdir(vroot):
        for n in sorted(names):
            candidates=[os.path.join(vroot,n,'_data')]
            try:
                candidates.extend(str(p) for p in Path(vroot).glob(f'*{n}*/_data'))
            except Exception: pass
            for p in candidates:
                if os.path.isdir(p) and walk_count(p,2000)>0:
                    hits.append(p)
    return sorted(set(hits))

compose_files=collect_named(names=COMPOSE_NAMES)
deploy_refs, deploy_dirs, deploy_meta=deployment_evidence()
history_refs, history_dirs, history_meta=history_evidence()
docker_rows, docker_refs, docker_dirs=raw_docker_evidence()
systemd_refs, systemd_dirs, systemd_meta=systemd_evidence()
all_refs=deploy_refs|history_refs|docker_refs|systemd_refs
all_dirs=deploy_dirs|history_dirs|docker_dirs|systemd_dirs

candidates=[]
for path in compose_files:
    text=read_text(path); lc=text.lower(); parent=os.path.realpath(os.path.dirname(path))
    score=0; reasons=[]
    direct_openclaw=bool(re.search(r'openclaw|open[ _-]?claw|claw gateway',lc))
    whatsapp=bool(re.search(r'whatsapp|baileys|linked.?device',lc))
    if direct_openclaw: score+=35; reasons.append('direct_openclaw_reference')
    if whatsapp: score+=15; reasons.append('direct_whatsapp_reference')
    if re.search(r'(?m)^\s*(?:image:|container_name:|services:)',text): score+=10; reasons.append('compose_structure')
    if re.search(r'restart:\s*(?:unless-stopped|always)',lc): score+=5; reasons.append('persistent_restart_policy')

    env_text=''
    for ep in [os.path.join(parent,'.env'),os.path.join(parent,'openclaw.env')]:
        env_text += '\n'+read_text(ep)
    if re.search(r'openclaw|open[ _-]?claw|claw gateway',env_text,re.I): score+=10; reasons.append('adjacent_env_openclaw_signal')
    if re.search(r'whatsapp|baileys|linked.?device|session',env_text,re.I): score+=5; reasons.append('adjacent_env_session_signal')

    norm=os.path.normpath(path)
    if norm in docker_refs: score+=45; reasons.append('historical_docker_compose_reference')
    if norm in deploy_refs: score+=35; reasons.append('deployment_script_compose_reference')
    if norm in systemd_refs: score+=30; reasons.append('systemd_compose_reference')
    if norm in history_refs: score+=20; reasons.append('shell_history_compose_reference')
    if parent in all_dirs: score+=20; reasons.append('proven_working_directory')

    binds=parse_bind_sources(text,parent)
    durable=[p for p in binds if walk_count(p,2000)>0]
    if durable: score+=30; reasons.append('durable_bind_state')
    volumes=named_volume_state(text)
    if volumes: score+=25; reasons.append('named_volume_state')
    sessions=session_state_near(parent)
    if sessions: score+=25; reasons.append('nearby_session_state')

    low=path.lower()
    if re.search(r'/(?:state-snapshots|backup|backups|old|archive|pre-update)(?:/|$)',low):
        score-=35; reasons.append('snapshot_or_backup_penalty')
    mtime=safe_mtime(path)
    candidates.append({
        'path':path,'score':max(0,min(score,100)),'mtime':mtime,'reasons':reasons,
        'bind_sources':binds,'durable_bind_sources':durable,'named_volume_state_paths':volumes,
        'session_state_metadata':sessions,'direct_openclaw_reference':direct_openclaw,
        'direct_whatsapp_reference':whatsapp,
    })

candidates.sort(key=lambda x:(-x['score'],-x['mtime'],x['path']))

def has_provenance(c):
    return any(r in c['reasons'] for r in (
        'historical_docker_compose_reference','deployment_script_compose_reference',
        'systemd_compose_reference','shell_history_compose_reference','proven_working_directory'))

def has_state(c):
    return any(r in c['reasons'] for r in ('durable_bind_state','named_volume_state','nearby_session_state'))

eligible=[c for c in candidates if c['score']>=min_score and has_provenance(c) and has_state(c)]
if len(eligible)==1:
    decision={'code':0,'class':'SAFE_CORRELATED_COMPOSE_CANDIDATE','candidate':eligible[0]}
elif len(eligible)>1:
    # A unique >=15 point lead is accepted only if it also carries strong provenance.
    top,second=eligible[0],eligible[1]
    strong_top=any(r in top['reasons'] for r in ('historical_docker_compose_reference','deployment_script_compose_reference','systemd_compose_reference'))
    if strong_top and top['score']-second['score']>=15:
        decision={'code':0,'class':'SAFE_CORRELATED_COMPOSE_CANDIDATE','candidate':top,'runner_up':second}
    else:
        decision={'code':25,'class':'FORENSICS_AMBIGUOUS_CORRELATED_CANDIDATES','candidates':eligible[:10]}
else:
    # Detect the common case where an authoritative deploy script exists but no
    # compose target can be proven. This is informative, not executable.
    deploy_only=bool(deploy_meta)
    decision={'code':24,'class':'FORENSICS_REQUIRED_NO_CORRELATED_COMPOSE','candidate':None,'deploy_script_evidence':deploy_only}

report={
    'engine':'openclaw_runtime_provenance_correlator_v1','min_score':min_score,
    'secrets_redacted':True,'mutated_runtime':False,
    'compose_candidate_count':len(candidates),'candidates':candidates[:40],
    'deployment_scripts':deploy_meta[:40],'history_metadata':history_meta,
    'historical_docker_candidates':docker_rows[:30],
    'systemd_units':systemd_meta[:40],
    'decision':decision,
}
Path(report_path).write_text(json.dumps(report,indent=2,sort_keys=True),encoding='utf-8')
Path(decision_path).write_text(json.dumps(decision,indent=2,sort_keys=True),encoding='utf-8')
print(json.dumps(report,indent=2,sort_keys=True))
PY

echo OPENCLAW_RUNTIME_CORRELATOR_ENGINE=PROVENANCE_V1
CLASS="$(python3 - "$DECISION" <<'PY'
import json,sys
print((json.load(open(sys.argv[1],encoding='utf-8')) or {}).get('class',''))
PY
)"
CODE="$(python3 - "$DECISION" <<'PY'
import json,sys
print((json.load(open(sys.argv[1],encoding='utf-8')) or {}).get('code',99))
PY
)"
echo "OPENCLAW_RUNTIME_CORRELATOR_DECISION=$CLASS"
if [[ "$CODE" == 0 ]]; then
  CANDIDATE="$(python3 - "$DECISION" <<'PY'
import json,sys
c=(json.load(open(sys.argv[1],encoding='utf-8')) or {}).get('candidate') or {}
print(c.get('path',''))
PY
)"
  SCORE="$(python3 - "$DECISION" <<'PY'
import json,sys
c=(json.load(open(sys.argv[1],encoding='utf-8')) or {}).get('candidate') or {}
print(c.get('score',0))
PY
)"
  echo "OPENCLAW_CORRELATED_COMPOSE=$CANDIDATE"
  echo "OPENCLAW_CORRELATED_SCORE=$SCORE"
  echo OPENCLAW_RUNTIME_CORRELATION=SAFE_CANDIDATE_FOUND
  exit 0
fi

echo OPENCLAW_RUNTIME_CORRELATION=FORENSICS_REQUIRED
exit "$CODE"
