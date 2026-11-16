#!/usr/bin/env python3
"""Reconcile completed late-ON audit and response fields; no network/model/code execution."""
from pathlib import Path
from collections import Counter
import hashlib,json,datetime
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
base=ROOT/'runs/csp-thinking_on16-evaluation-s1-late'
snapshot=HERE/'snapshot-01-9a19553c3ca4.json'
audit=json.loads(snapshot.read_text());meta=json.loads((base/'metadata.json').read_text());rows=json.loads((base/'summary.json').read_text())
assert audit['verified']and audit['complete']and audit['completed_cases']==len(rows)==96
assert meta['verified']and not meta['incomplete']and not meta['faults']and not meta['source_changed_during_run']
assert all(sha(ROOT/n)==h for n,h in audit['input_sha256'].items())
counts=Counter();arms={};errors=Counter()
for row in rows:
 a=arms.setdefault(row['arm'],dict(cases=0,solved=0));a['cases']+=1;a['solved']+=row['solved']
 for line in Path(row['events']).read_text().splitlines():
  e=json.loads(line)
  if e['type']!='request_end':continue
  review=e['stage'].startswith('review-');prefix='review_'if review else'assignment_'
  counts[prefix+'responses']+=1;counts[prefix+'finish_'+str(e.get('finish_reason'))]+=1
  counts[prefix+'nonempty_reasoning']+=bool(e.get('reasoning'));counts[prefix+'nonempty_content']+=bool(e.get('response'))
  if e.get('error'):errors[e['error']]+=1
assert len(arms)==8 and all(v['cases']==12 for v in arms.values())
assert counts['assignment_responses']==counts['assignment_finish_length']==counts['assignment_nonempty_reasoning']==1464
assert counts['assignment_nonempty_content']==0 and counts['review_responses']==counts['review_finish_stop']==counts['review_nonempty_content']==72
assert errors=={'ValueError: response content must be a string':1464}
costs={k:sum(r[k]for r in rows)for k in ['prompt_tokens','completion_tokens','server_prompt_tokens','server_completion_tokens']}
assert costs['prompt_tokens']==costs['server_prompt_tokens']and costs['completion_tokens']==costs['server_completion_tokens']
report=dict(verified=True,complete=True,completed_cases=96,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),classification=audit['classification'],proof_policy_audit_sha256=sha(snapshot),policy_checks=dict(completed_cases=96,candidate_ancestry_and_dedup_checks=1464,endpoint_intervals_nonoverlap=True,auditor_sha256='8b5a2dd08e7dd70e1f7625065dd8d3cf46a2bd75dbda5d8cea88a8b7fb76af3b'),counts=audit['counts'],by_arm=arms,response_fields=dict(counts),response_parser_errors=dict(errors),costs=costs,batch_wall_seconds=meta['batch_wall_seconds'],input_sha256=audit['input_sha256'],source_audit_sha256=sha(Path(__file__)),interpretation=['Late exploratory one-seed12-graph profile, not pooled with OFF studies or original automatic ON time-skip.','All assignment calls returned separate reasoning but no answer content at4096-token length limit. These are received-response parse/format failures, not transport faults.','All72 critic calls returned content and stop; no valid assignment permits a derived consensus.','No tasks filtered, no successful assignment proofs, all1536 calls completed and all96 server costs known.','Finite suite outcome only; no architecture winner or universal impossibility claim.'])
p=HERE/'FINAL_AUDIT.json'
with p.open('x')as f:json.dump(report,f,indent=2);f.write('\n')
manifest={str(p.relative_to(HERE)):sha(p)for p in HERE.rglob('*')if p.is_file()}
with(HERE/'ARTIFACT_MANIFEST.json').open('x')as f:json.dump(dict(files=manifest,scope='Audit artifacts and exact auditor source snapshots; frozen/runtime inputs separately bound inFINAL_AUDIT'),f,indent=2);f.write('\n')
print(json.dumps(dict(path=str(p.relative_to(ROOT)),sha256=sha(p),verified=True,complete=True,completed_cases=96,costs=costs)))
