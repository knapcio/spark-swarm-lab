"""Authored fake execute only; never invokes worker, HTTP, model or candidate code."""
import contextlib,io,json,sys,tempfile,threading,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'.runtime/nemotron72-followup-source'
sys.path.insert(0,str(SOURCE))
import run_followup72 as runner

def main():
    barrier=threading.Barrier(4);lock=threading.Lock();entered=[];fault=threading.Event()
    def execute(case,deadline_seconds):
        with lock:entered.append(dict(slot=case['slot'],position=case['position'],after_fault=fault.is_set()))
        if case['position']<4:
            barrier.wait(timeout=2)
            if case['slot']==0:
                fault.set();raise OSError('authored local controller failure')
            fault.wait(2);time.sleep(.03)
        return dict(task_id=case['task_id'],split=case['split'],arm=case['arm'],seed=case['seed'],endpoint=case['endpoint'],events=case['events'],controller_error=None,malformed_lines=0,infrastructure_failures=0,returncode=0,controller_stop=False,calls=1,completed_calls=1,unfinished_calls=0,deadline=False,status='complete',server_idle_after=True,server_cost_known=True)
    with tempfile.TemporaryDirectory()as temp:
        temp=Path(temp);protocol=json.loads(runner.PROTOCOL.read_text());protocol['status']='FROZEN';(temp/'protocol.json').write_text(json.dumps(protocol))
        endpoints=[f'http://127.0.0.1:{port}/v1'for port in range(18081,18085)]
        admission=dict(verified=True,verified_utc=datetime.now(timezone.utc).isoformat(),source_sha256={'authored':'fixture'},endpoints=endpoints,runtime_identical_to_study_v032=True)
        (temp/'admission.json').write_text(json.dumps(admission))
        with patch.object(runner,'PROTOCOL',temp/'protocol.json'),patch.object(runner,'source_hashes',return_value={'authored':'fixture'}),patch.object(runner,'execute',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
            code=runner.main(['--run','--output',str(temp/'output'),'--admission',str(temp/'admission.json')])
        metadata=json.loads((temp/'output/metadata.json').read_text())
        result=dict(returncode=code,execute_entries=entered,executions_started_after_fault=sum(x['after_fault']for x in entered),completed_cases=metadata['completed_cases'],errors=metadata['errors'])
        print(json.dumps(result,indent=2))
if __name__=='__main__':main()
