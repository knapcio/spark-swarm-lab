"""Exactly the frozen optional API-format probes; no model calls without --run."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())

def require(ok, message):
    if not ok: raise RuntimeError(message)

def write(path, value):
    with path.open('x') as stream: json.dump(value, stream, indent=2, ensure_ascii=False)

def valid(payload, schema):
    if type(payload) is not dict or set(payload) != set(schema['required']): return False
    if 'assignment' in payload:
        values = payload['assignment']; spec = schema['properties']['assignment']
        return (type(values) is list and spec['minItems'] <= len(values) <= spec['maxItems']
            and all(type(v) is int and v in spec['items']['enum'] for v in values))
    text = payload.get('critique'); spec = schema['properties']['critique']
    return type(text) is str and spec['minLength'] <= len(text) <= spec['maxLength']

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', action='store_true'); args = parser.parse_args()
    if not args.run:
        print(json.dumps(dict(mode='plan', maximum_probes=3, output='.runtime/guided-schema-qualification-v1', model_calls=0))); return 0
    planpath = ROOT/'.runtime/GUIDED_SCHEMA_PROBE_PLAN.json'
    require(sha(planpath) == '1638edfe5dea9f2f8c77867fb38df0c69a6ab6c5f708417215959c0b3fbf2e92', 'Frozen probe plan differs')
    plan = read(planpath); frozen = read(ROOT/'.runtime/CSP_GUIDED_FROZEN_SOURCE.json'); source = Path(frozen['source_worktree'])
    require(subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip() == frozen['revision'], 'Wrong guided source')
    require(not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],text=True).strip(), 'Guided source dirty')
    require(all(sha(source/n) == h for n,h in frozen['source_identity']['sha256'].items()), 'Guided source pins differ')
    for rel in ['runs/csp-thinking_on16-evaluation-s1-late/metadata.json','runs/program-review-elites4-v1.1/metadata.json','runs/program-review-confirmation-v1.1/metadata.json']:
        value = read(ROOT/rel); require(value.get('verified') is True and not value.get('incomplete') and not value.get('faults'), 'Prior phase incomplete: '+rel)
    sys.path.insert(0,str(ROOT)); helperpath=ROOT/'.runtime/post_throughput_overnight.py'
    require(sha(helperpath) == 'a850fb38f2fe9579863f8d41bdfae8aa045d9300cc736dd1394fcc4dcd3c8e6e', 'Read-only helper differs')
    spec=importlib.util.spec_from_file_location('readonly_post',helperpath); helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    out=ROOT/'.runtime/guided-schema-qualification-v1'; out.mkdir()
    before=helper.fleet_check(out,'fleet-before-probes')
    for node in before: helper.no_grader_leftovers(node['host'])
    recent=read(ROOT/'.runtime/program-review-confirmation-admission-v1.1/manual-admission.json')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(recent['checked_utc'])).total_seconds()
    require(recent['verified'] and not recent['model_switch_started'] and not recent['feature_switch_started'] and 0 <= age <= 900, 'Fresh pre-feature runtime admission required')
    rows=[]; errors=[]; began=time.monotonic()
    metadata=dict(source_revision=frozen['revision'],source_sha256=frozen['source_identity']['sha256'],plan_sha256=sha(planpath),driver_sha256=sha(__file__),prior_admission_sha256=sha(ROOT/'.runtime/program-review-confirmation-admission-v1.1/manual-admission.json'),started_utc=datetime.now(timezone.utc).isoformat(),maximum_calls=3,mode='API format qualification only; no graph quality inference',failure_policy='Stop on first failed probe; never add probes, relax schemas or change runtime',fleet_before=before)
    write(out/'admission.json',metadata)
    for probe in plan['probes']:
        material=f"{plan['seed_label']}:{probe['agent_id']}:{probe['stage']}:{probe['prompt']}"
        body=dict(model=plan['model'],messages=[dict(role='system',content=plan['system_prompt']),dict(role='user',content=probe['prompt'])],max_tokens=plan['max_tokens'],temperature=plan['temperature'],seed=int.from_bytes(hashlib.sha256(material.encode()).digest()[:4],'big'),stream=False,chat_template_kwargs=dict(enable_thinking=False),structured_outputs=dict(json=probe['schema']))
        rawbody=json.dumps(body).encode(); row=dict(id=probe['id'],request=body,request_sha256=hashlib.sha256(rawbody).hexdigest(),schema_valid=False); start=time.monotonic()
        try:
            request=urllib.request.Request(plan['endpoint']+'/chat/completions',data=rawbody,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=plan['request_timeout_seconds']) as response: raw=response.read(); row['http_status']=response.status
            data=json.loads(raw); row.update(response=data,response_sha256=hashlib.sha256(raw).hexdigest())
            content=data['choices'][0]['message']['content']; payload=json.loads(content)
            row.update(payload=payload,schema_valid=valid(payload,probe['schema']))
            require(row['schema_valid'], 'Response violates exact frozen schema')
        except Exception as exc:
            row['error_classification']=type(exc).__name__
            if isinstance(exc,urllib.error.HTTPError):
                raw=exc.read(65536); row.update(http_status=exc.code,http_error_body=raw.decode('utf-8','replace'),http_error_sha256=hashlib.sha256(raw).hexdigest()); exc.close()
            errors.append(dict(probe=probe['id'],classification=type(exc).__name__))
        row['wall_seconds']=time.monotonic()-start; rows.append(row); write(out/(probe['id']+'.json'),row)
        if errors: break
    try: after=helper.fleet_check(out,'fleet-after-probes')
    except Exception as exc: after=None; errors.append(dict(boundary='final_fleet',classification=type(exc).__name__))
    unchanged=all(sha(source/n) == h for n,h in frozen['source_identity']['sha256'].items())
    result=dict(metadata,rows=rows,executed_calls=len(rows),qualified=len(rows)==3 and not errors and unchanged and all(r['schema_valid'] for r in rows),errors=errors,source_unchanged=unchanged,fleet_after=after,wall_seconds=time.monotonic()-began,completed_utc=datetime.now(timezone.utc).isoformat())
    write(out/'result.json',result); print(json.dumps({k:result[k] for k in ['executed_calls','qualified','errors','wall_seconds']})); return 0 if result['qualified'] else 1

if __name__=='__main__': raise SystemExit(main())
