"""Synthetic offline reference-report checks; never execute candidate/model code."""
from contextlib import redirect_stdout
import copy,hashlib,io,json
from pathlib import Path
import unittest
from unittest.mock import patch
import report_reference_deepseek as r

class ReferenceReportTests(unittest.TestCase):
    def test_plan_never_reads_partial_outcomes_or_runs_bootstrap(self):
        with patch.object(r,'read')as read,patch.object(r,'validate')as validate,patch.object(r.ag,'report_for')as stats,redirect_stdout(io.StringIO())as out:
            self.assertEqual(r.main(['/not-present']),0);self.assertEqual(json.loads(out.getvalue())['cases'],126)
            read.assert_not_called();validate.assert_not_called();stats.assert_not_called()

    def test_incomplete_or_unaudited_rejected_and_no_native_verified_flag_required(self):
        meta=dict(completed_cases=126,attempts=126,incomplete=False,errors=[],completed_utc='2026-11-16',source_changed_during_run=False,provider='WRONG')
        audit=dict(verified=True,complete=True,completed_cases=126)
        for key,value in [('completed_cases',125),('incomplete',True),('errors',['fault']),('source_changed_during_run',True),('UNCHANGED',None)]:
            m=copy.deepcopy(meta)
            if key!='UNCHANGED':m[key]=value
            with self.subTest(key=key),patch.object(r,'read',side_effect=[m,audit]),patch.object(r,'audit_bound'):
                with self.assertRaisesRegex(ValueError,'provider'if key=='UNCHANGED'else'incomplete'):r.validate(Path('/not-present'),Path('/audit'))
        with patch.object(r,'read',side_effect=[meta,dict(audit,verified=False)]):
            with self.assertRaisesRegex(ValueError,'audit'):r.validate(Path('/not-present'),Path('/audit'))

    def test_arithmetic_root_legal_ancestry_and_false_reward(self):
        case={'command':['--puzzle','2,3,7:5']};events=[dict(type='node',node_id='r',parent_id=None,state=['2','3','7']),dict(type='node',node_id='c',parent_id='r',state=['7','5']),dict(type='proposal',legal=True,parent_id='r',child_node_id='c',child_state=['7','5'],action={'i':0,'j':1,'op':'+'}),dict(type='reward',node_id='c',solved=True)]
        r.arithmetic(case,{'solved':True},events)
        for change in ('root','action','orphan','reward'):
            broken=copy.deepcopy(events)
            if change=='root':broken[0]['state']=['2','3','8']
            if change=='action':broken[2]['action']['i']=2
            if change=='orphan':broken.pop(2)
            if change=='reward':broken[-1]['node_id']='r'
            with self.subTest(change=change),self.assertRaises(ValueError):r.arithmetic(case,{'solved':True},broken)

    def test_coding_one_frozen_holdout_payload_authority_and_no_candidate(self):
        code='def f(x): return x';cid=hashlib.sha256(code.encode()).hexdigest();task='synthetic';private={task:dict(feedback_tests=[{'args':[1]}],holdout_tests=[{'args':[2]}])};public={task:{'function_name':'f'}}
        context=dict(source_revision=r.CBC,outer_grader_sha256=r.OUTER,image=r.IMAGE,grading_authority='outer_parent',oracle_sent_to_child=False)
        events=[dict(type='request_start',event_id=1),dict(type='code_candidate',event_id=2,candidate_id=cid,code=code),dict(type='candidate_selected',event_id=3,candidate_id=cid,holdout_seen=False)]
        tests=private[task]['holdout_tests'];payload=json.dumps(dict(code=code,function_name='f',calls=[dict(args=t['args'],kwargs={})for t in tests],timeout=10),allow_nan=False)
        report=dict(status='passed',grading_authority='outer_parent',oracle_sent_to_child=False,cleanup_ok=True,provenance='candidate',child_payload_sha256=hashlib.sha256(payload.encode()).hexdigest())
        events += [dict(type='evaluation_end',event_id=4,phase='holdout',candidate_id=cid,infrastructure_error=False,report=report),dict(type='reward',event_id=5,solved=True)]
        r.coding({'task_id':task},{'solved':True},events,context,private,public)
        for change in ('before','retry','payload','cleanup','oracle'):
            broken=copy.deepcopy(events)
            if change=='before':broken[3]['event_id']=0
            if change=='retry':broken.append(dict(type='request_start',event_id=6))
            if change=='payload':broken[3]['report']['child_payload_sha256']='wrong'
            if change=='cleanup':broken[3]['report']['cleanup_ok']=False
            if change=='oracle':broken[3]['report']['oracle_sent_to_child']=True
            with self.subTest(change=change),self.assertRaises(ValueError):r.coding({'task_id':task},{'solved':True},broken,context,private,public)
        skipped=[dict(type='candidate_selected',event_id=1,candidate_id=None,holdout_seen=False),dict(type='reward',event_id=2,solved=False)]
        r.coding({'task_id':task},{'solved':False},skipped,context,private,public)

if __name__=='__main__':unittest.main()
