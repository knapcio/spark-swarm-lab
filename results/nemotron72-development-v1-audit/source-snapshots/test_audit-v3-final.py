"""Authored fake HTTP fixtures only; no endpoint, generated code or puzzle search."""
import contextlib,copy,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import audit
sys.path.insert(0,str(audit.SOURCE))
import followup72_worker,run_benchmark

class AuditorTests(unittest.TestCase):
    def fixture(self,arm):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);trace=Path(temp.name)/'events.jsonl'
        task=dict(id='authored',split='development',numbers=[2,3,7,11],target=5)
        case=dict(task_id='authored',split='development',arm=arm,seed=1,endpoint='http://offline.invalid/v1',events=str(trace))
        calls=[]
        def transport(request,timeout):
            body=json.loads(request.data);calls.append(body);scribe=arm.startswith('scribe_');draft=scribe and len(calls)==1
            move=dict(a=2,b=3,op='+')if arm.startswith('value_')else dict(i=0,j=1,op='+')
            content=None if draft else json.dumps(dict(moves=[move]));tokens=7936 if draft else 256 if scribe else 12
            response=dict(model='nemotron-lightning',choices=[dict(finish_reason='length'if draft else'stop',message=dict(content=content,reasoning_content='α'*4500+'END'if draft else'authored notes'))],usage=dict(prompt_tokens=10,completion_tokens=tokens,total_tokens=10+tokens))
            return io.BytesIO(json.dumps(response).encode())
        with patch('urllib.request.urlopen',side_effect=transport),contextlib.redirect_stdout(io.StringIO()):
            code=followup72_worker.main(['--variant',arm,'--puzzle','2,3,7,11:5','--endpoint',case['endpoint'],'--seed','1','--events',str(trace),'--run'])
        self.assertEqual(code,0);events=[json.loads(x)for x in trace.read_text().splitlines()];row=run_benchmark.metrics(events)
        row.update(controller_error=None,malformed_lines=0,returncode=0,controller_stop=False,server_idle_after=True,server_cost_known=True,server_prompt_tokens=row['prompt_tokens'],server_completion_tokens=row['completion_tokens'],server_metrics_before=dict(timestamp_utc='2026-01-01T00:00:00+00:00',running=0,waiting=0,prompt=0,completion=0),server_metrics_after=dict(timestamp_utc='2026-01-01T00:00:01+00:00',running=0,waiting=0,prompt=row['prompt_tokens'],completion=row['completion_tokens']))
        return case,row,task,events
    def mutate(self,case,events):Path(case['events']).write_text(''.join(json.dumps(x)+'\n'for x in events))
    def test_all_seven_authored_profiles_replay_and_wire_match(self):
        for arm in('index_original','index_explicit','value_original','value_explicit','scribe_full','scribe_tail','scribe_empty'):
            with self.subTest(arm=arm):
                case,row,task,_=self.fixture(arm);result=audit.check_case(case,row,task);self.assertTrue(result['solved']);self.assertEqual(result['calls'],2 if arm.startswith('scribe_')else 1)
    def test_wrong_wire_seed_rejected(self):
        case,row,task,events=self.fixture('index_original');next(x for x in events if x['type']=='request_start')['request_body']['seed']+=1;self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'wire body'):audit.check_case(case,row,task)
    def test_wrong_parent_hash_rejected(self):
        case,row,task,events=self.fixture('scribe_full');next(x for x in events if x['type']=='request_start'and x['stage']=='scribe')['parent_request_id']='another-case';self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'notes lineage'):audit.check_case(case,row,task)
    def test_cap_overrun_is_positive_protocol_fault(self):
        case,row,task,events=self.fixture('index_original');end=next(x for x in events if x['type']=='request_end')
        for usage in(end['usage'],end['raw_usage']):usage['completion_tokens']=8193;usage['total_tokens']=8203
        end['completion_tokens_charged']=8193;self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'POSITIVE_PROTOCOL_VIOLATION'):audit.check_case(case,row,task)
    def test_false_arithmetic_child_rejected(self):
        case,row,task,events=self.fixture('value_original');next(x for x in events if x['type']=='proposal')['child_state'][-1]='999';self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'compiler or result drift'):audit.check_case(case,row,task)
    def test_wrong_boolean_reward_rejected(self):
        case,row,task,events=self.fixture('index_original');next(x for x in events if x['type']=='reward')['solved']=False;self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'reward lacks'):audit.check_case(case,row,task)
    def test_controlled_deadline_keeps_unfinished_usage_unknown(self):
        case,row,task,events=self.fixture('index_original')
        cut=next(i for i,x in enumerate(events)if x['type']=='request_start')
        events=events[:cut+1];self.mutate(case,events)
        row.update(run_benchmark.metrics(events,deadline=True));row.update(returncode=-15,controller_stop=True,server_prompt_tokens=10,server_completion_tokens=6000)
        row['server_metrics_after'].update(prompt=10,completion=6000)
        result=audit.check_case(case,row,task)
        self.assertEqual(result['unfinished_calls'],1);self.assertFalse(result['client_usage_complete']);self.assertFalse(result['solved']);self.assertTrue(result['deadline'])
    def test_omitted_legal_replay_step_rejected_even_for_negative_claim(self):
        case,row,task,events=self.fixture('index_original')
        events=[x for x in events if x['type']!='proposal']
        for index,event in enumerate(events,1):event['event_id']=index
        self.mutate(case,events)
        with self.assertRaisesRegex(ValueError,'omitted sampled-plan replay'):audit.check_case(case,row,task)
    def test_literal_operands_no_swap_repair_or_duplicate_use(self):
        for state,move in[((2,3),dict(a=2,b=2,op='+')),((1,150),dict(a=1,b=150,op='-')),((2,3),dict(a=True,b=3,op='+'))]:
            with self.assertRaises(ValueError):audit.action(state,move,True)
        self.assertEqual(audit.action((2,2,7),dict(a=2,b=2,op='+'),True)[0],(7,4))
if __name__=='__main__':unittest.main()
