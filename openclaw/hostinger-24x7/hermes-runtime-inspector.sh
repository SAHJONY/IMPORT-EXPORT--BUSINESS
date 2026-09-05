#!/usr/bin/env bash
set -euo pipefail

redact(){ sed -E 's/(token|secret|password|authorization|api[_-]?key)[=:][^[:space:]]+/\1=[REDACTED]/Ig'; }
section(){ printf '\n=== %s ===\n' "$1"; }

section 'HERMES INSTALLATION'
for p in /usr/local/bin/hermes /usr/bin/hermes /root/.local/bin/hermes /root/.hermes/hermes-agent; do
  [[ -e "$p" ]] && stat -c '%n|type=%F|mode=%a|mtime=%y' "$p" 2>/dev/null || true
done
command -v hermes 2>/dev/null | sed 's/^/hermes_bin=/' || echo hermes_bin=NOT_ON_PATH

section 'HERMES CLI SURFACE'
if command -v hermes >/dev/null 2>&1; then
  (hermes --version 2>&1 || true) | head -n 8 | redact
  (hermes --help 2>&1 || true) | head -n 120 | redact
elif [[ -f /root/.hermes/hermes-agent/pyproject.toml ]]; then
  grep -nE '^\[project\.scripts\]|^[A-Za-z0-9_.-]+[[:space:]]*=' /root/.hermes/hermes-agent/pyproject.toml | head -n 80 | redact
fi

section 'ACTIVE HERMES PROCESSES'
ps -eo pid,ppid,user,etimes,comm,args --no-headers \
  | grep -Ei '[h]ermes|[o]penclaw' \
  | sed -E 's/(token|secret|password|authorization|api[_-]?key)[= ][^[:space:]]+/\1 [REDACTED]/Ig' \
  | head -n 120 || true

section 'SYSTEMD HERMES / OPENCLAW UNITS'
systemctl list-unit-files --type=service --type=timer --no-pager 2>/dev/null \
  | grep -Ei 'hermes|openclaw|whatsapp' | head -n 120 || true
systemctl list-units --type=service --type=timer --all --no-pager 2>/dev/null \
  | grep -Ei 'hermes|openclaw|whatsapp' | head -n 120 || true

section 'DOCKER HERMES / OPENCLAW'
docker ps -a --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' 2>/dev/null \
  | grep -Ei 'hermes|openclaw|claw' | head -n 80 || true

section 'HERMES COMPOSE STRUCTURE'
compose=/root/.hermes/hermes-agent/docker-compose.yml
if [[ -f "$compose" ]]; then
  python3 - "$compose" <<'PY'
import sys
p=sys.argv[1]
lines=open(p, encoding='utf-8', errors='replace').read().splitlines()
in_services=False
for line in lines:
    if line.startswith('services:'):
        in_services=True; print('services:'); continue
    if in_services:
        if line and not line.startswith(' '): break
        if line.startswith('  ') and not line.startswith('    ') and line.rstrip().endswith(':'):
            print(line.rstrip())
        elif any(k in line for k in ('image:', 'command:', 'entrypoint:', 'ports:', 'network_mode:')):
            clean=line
            if '${' in clean: clean=clean.split('${',1)[0]+'[ENV_REDACTED]'
            print(clean.rstrip())
PY
else
  echo compose_missing=1
fi

section 'HERMES CONFIG KEY PATHS ONLY'
python3 - <<'PY'
import json, os
for p in ['/root/.hermes/config.json','/root/.hermes/settings.json','/root/.hermes/auth.json']:
    if not os.path.isfile(p): continue
    print(f'--- {p}')
    try: data=json.load(open(p, encoding='utf-8'))
    except Exception as e:
        print('parse='+type(e).__name__); continue
    def walk(v, prefix=''):
        if isinstance(v, dict):
            for k, child in v.items():
                q=f'{prefix}.{k}' if prefix else str(k)
                print(q)
                if isinstance(child,(dict,list)): walk(child,q)
        elif isinstance(v,list):
            for i, child in enumerate(v[:10]):
                if isinstance(child,(dict,list)): walk(child,f'{prefix}[]')
    walk(data)
PY

section 'HERMES WHATSAPP ENTRYPOINT REFERENCES'
base=/root/.hermes/hermes-agent
if [[ -d "$base" ]]; then
  grep -RInE --exclude-dir='.git' --exclude-dir='node_modules' --exclude='*.pyc' \
    'whatsapp|gateway.*start|start.*gateway|uvicorn|gunicorn|FastAPI|listen|port' \
    "$base/gateway" "$base/hermes_cli" "$base/pyproject.toml" 2>/dev/null \
    | head -n 180 | redact || true
fi

section 'MODEL CONFIGURATION NAMES ONLY'
for f in /etc/openclaw-openai.env /etc/openclaw-nvidia.env /etc/openclaw-sahjony-bridge.env; do
  [[ -f "$f" ]] || continue
  echo "--- $f"
  cut -d= -f1 "$f" | grep -E '^[A-Z0-9_]+$' | sort -u
 done
if [[ -f /var/lib/sahjony-openclaw-state/openclaw.json ]]; then
  python3 - <<'PY'
import json
p='/var/lib/sahjony-openclaw-state/openclaw.json'
d=json.load(open(p, encoding='utf-8'))
model=((d.get('agents') or {}).get('defaults') or {}).get('model') or {}
print('openclaw_primary_model='+str(model.get('primary') or ''))
print('openclaw_fallback_count='+str(len(model.get('fallbacks') or [])))
PY
fi

echo HERMES_RUNTIME_INSPECTOR_COMPLETE=1
