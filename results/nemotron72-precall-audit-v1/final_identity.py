"""Identity-only frozen follow-up binding; no network, models or candidate execution."""
import ast,copy,hashlib,json,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
RECEIPT=ROOT/'.runtime/NEMOTRON72_FROZEN_SOURCE_V1.json';SOURCE=ROOT/'.runtime/nemotron72-followup-source';REV='638b9f335a7aa7011a9b7d122abcaa04f45e17a5'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
git=lambda *args:subprocess.check_output(['git',*args],cwd=SOURCE,text=True)
receipt=json.loads(RECEIPT.read_text());clearance=json.loads((OUT/'PROVISIONAL_CLEARANCE.json').read_text())
assert receipt['revision']==REV==git('rev-parse','HEAD').strip()==git('rev-parse',receipt['tag']+'^{}').strip()
assert not git('status','--porcelain')
assert receipt['precall_clearance_sha256']==sha(OUT/'PROVISIONAL_CLEARANCE.json')
pins={**receipt['source_sha256'],**receipt['test_sha256']}
assert len(receipt['source_sha256'])==10 and len(receipt['test_sha256'])==3
for name,digest in pins.items():
    assert sha(SOURCE/name)==digest
    assert subprocess.check_output(['git','show',REV+':'+name],cwd=SOURCE)==(SOURCE/name).read_bytes()
    if name!='FOLLOWUP72_DEVELOPMENT_PLAN.json':assert digest==clearance['source_sha256'][name]
protocol=json.loads((SOURCE/'FOLLOWUP72_DEVELOPMENT_PLAN.json').read_text())
assert protocol['status']=='FROZEN'and protocol['frozen_utc']==receipt['frozen_utc']
assert protocol['implementation_bindings']['precall_clearance_sha256']==sha(OUT/'PROVISIONAL_CLEARANCE.json')
# Reverse only the declared metadata freeze and reproduce the reviewed PROPOSED bytes/hash.
prior=copy.deepcopy(protocol);prior['status']='PROPOSED';prior.pop('frozen_utc')
bindings=prior['implementation_bindings'];bindings.pop('precall_clearance_sha256');bindings.pop('freeze_contract');client=bindings.pop('client')
base=json.loads(git('show',REV+'^:FOLLOWUP72_DEVELOPMENT_PLAN.json'))
bindings['pending_before_FROZEN']=base['implementation_bindings']['pending_before_FROZEN'];bindings['client']=client
assert hashlib.sha256((json.dumps(prior,indent=2)+'\n').encode()).hexdigest()==clearance['source_sha256']['FOLLOWUP72_DEVELOPMENT_PLAN.json']
original=subprocess.check_output(['git','show','1a462213dd368cdfa664076399b5a458cdd1a40a:harness.py'],cwd=SOURCE)
assert original==(SOURCE/'harness.py').read_bytes()
sys.path.insert(0,str(SOURCE));import run_followup72 as runner
assert set(runner.SOURCES)==set(receipt['source_sha256'])
endpoints=[f'http://127.0.0.1:{port}/v1'for port in range(18081,18085)]
cases=runner.make_cases(json.loads(runner.DATASET.read_text()),Path('/unused-offline-plan'),endpoints)
assert len(cases)==168 and len({(c['task_id'],c['arm'],c['seed'])for c in cases})==168
assert Counter(c['slot']for c in cases)=={i:42 for i in range(4)}
assert set(Counter((c['seed'],c['arm'],c['slot'])for c in cases).values())=={2}
assert runner.schedule_sha(cases)==protocol['scheduling']['canonical_schedule_sha256']
plan_path=ROOT/'.runtime/nemotron72-development-plan-v1.json';saved=json.loads(plan_path.read_text())
assert runner.schedule_sha(saved['cases'])==runner.schedule_sha(cases)
assert all(c['command'][c['command'].index('--timeout')+1]=='210'and c['server_metrics']and not c['stop_on_solution']for c in cases)
assert receipt['quality_model_calls_before_freeze']==0 and receipt['runtime_admission']is False
for name,digest in pins.items():assert sha(SOURCE/name)==digest
result=dict(status='PASS',verified=True,complete=True,checked_utc=datetime.now(timezone.utc).isoformat(),source_revision=REV,source_tag=receipt['tag'],clean_worktree=True,frozen_receipt_path=str(RECEIPT.relative_to(ROOT)),frozen_receipt_sha256=sha(RECEIPT),source_sha256=receipt['source_sha256'],test_sha256=receipt['test_sha256'],provisional_clearance_sha256=sha(OUT/'PROVISIONAL_CLEARANCE.json'),implementation_and_test_bytes_unchanged_since_clearance=True,protocol_change='Only PROPOSED→FROZEN, frozen_utc, clearance hash and external freeze contract; reversing these reproduces exact prior protocol SHA.',original_harness_byte_identical=True,baseline_revision='1a462213dd368cdfa664076399b5a458cdd1a40a',matrix=dict(cases=168,tasks=8,variants=7,seeds=[1,2,3],cases_per_node=42,cases_per_variant_node_seed=2,schedule_sha256=runner.schedule_sha(cases),maximum_requests=240,maximum_completion_tokens_per_case=8192,whole_case_seconds=180,request_timeout_seconds=210),saved_plan_sha256=sha(plan_path),saved_plan_comparison='Case schedule only; historical source metadata in an earlier plan is not asserted current.',validation=dict(independently_checked_before_freeze={'focused_tests':16,'baseline_parity_fixtures':192,'controller_exception_extra_cases_after_fix':0,'mock_full_matrix':168,'mock_source_drift_admissions':7,'mock_proposed_gate_admissions':0},root_full_suite_receipt=receipt['validation'],full_suite_not_rerun_for_identity_only_binding=True),input_sha256={p.name:sha(p)for p in sorted(OUT.iterdir())if p.is_file()},limitations=clearance['interpretation']+['This is source/protocol clearance only. Fresh operational admission and root-controlled launch remain separate. No runtime/model/SSH/candidate execution was performed by this audit.'])
with(OUT/'FINAL_PRECALL.json').open('x')as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(dict(status='PASS',receipt_sha256=sha(RECEIPT),final_audit_sha256=sha(OUT/'FINAL_PRECALL.json'),source_revision=REV,cases=168),indent=2))
