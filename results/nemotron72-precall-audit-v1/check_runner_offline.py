"""Offline controller matrix/barrier/source-drift tests, all execute calls mocked."""
import contextlib,io,json,sys,tempfile,threading
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];SOURCE=ROOT/'.runtime/nemotron72-followup-source';sys.path.insert(0,str(SOURCE))
import run_followup72 as r

def check(drift=False,proposed=False):
    completed={};active=set();lock=threading.Lock();calls=[]
    def execute(case,deadline_seconds):
        assert deadline_seconds==180
        with lock:
            assert case['slot']not in active
            assert all(completed.get(b,0)==7 for b in range(case['block']))
            active.add(case['slot']);calls.append(case)
        row=dict(task_id=case['task_id'],split=case['split'],arm=case['arm'],seed=case['seed'],endpoint=case['endpoint'],events=case['events'],controller_error=None,malformed_lines=0,infrastructure_failures=0,returncode=0,controller_stop=False,calls=1,completed_calls=1,unfinished_calls=0,deadline=False,status='complete',server_idle_after=True,server_cost_known=True)
        with lock:active.remove(case['slot']);completed[case['block']]=completed.get(case['block'],0)+1
        return row
    hashes={'authored':'fixture'};changed={'authored':'changed'}
    sequence=iter([hashes,hashes,changed,changed]) if drift else None
    with tempfile.TemporaryDirectory()as temp:
        p=Path(temp);protocol=json.loads(r.PROTOCOL.read_text());protocol['status']='PROPOSED'if proposed else'FROZEN';(p/'protocol.json').write_text(json.dumps(protocol))
        endpoints=[f'http://127.0.0.1:{port}/v1'for port in range(18081,18085)]
        admission=dict(verified=True,verified_utc=datetime.now(timezone.utc).isoformat(),source_sha256=hashes,endpoints=endpoints,runtime_identical_to_study_v032=True);(p/'admission.json').write_text(json.dumps(admission))
        with patch.object(r,'PROTOCOL',p/'protocol.json'),patch.object(r,'source_hashes',side_effect=(lambda:next(sequence))if drift else lambda:hashes),patch.object(r,'execute',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            if proposed:
                try:r.main(['--run','--output',str(p/'output'),'--admission',str(p/'admission.json')])
                except ValueError as exc:assert str(exc)=='Protocol must be frozen before inference'
                else:raise AssertionError('PROPOSED unexpectedly admitted')
                assert not calls and not(p/'output').exists();return dict(proposed_gate=True,execute_calls=0)
            code=r.main(['--run','--output',str(p/'output'),'--admission',str(p/'admission.json')])
        meta=json.loads((p/'output/metadata.json').read_text())
        if drift:assert code==1 and len(calls)==7 and meta['errors']==[dict(reason='source_changed_before_block',block=1)]and meta['source_changed_during_run']
        else:assert code==0 and len(calls)==168 and not meta['incomplete']and not meta['errors']
        assert len(meta['attempted_case_events'])==len(calls)
        return dict(verified=True,execute_calls=len(calls),source_drift=drift,attempts_logged=len(calls),all_previous_blocks_complete_before_next=True)
print(json.dumps(dict(full_cohort=check(),source_drift=check(drift=True),proposed_gate=check(proposed=True)),indent=2))
