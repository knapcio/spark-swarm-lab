"""Synthetic offline validator checks, never real grades or model/program execution."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from csp_tasks import PROTOCOL, graph_digest, verify_assignment
import report_program_confirmation as r


def write(path, value): path.write_text(json.dumps(value))

def fixture(root):
    directory=root/'cohort';directory.mkdir()
    tasks=[dict(id='tiny-'+str(i),split='evaluation',vertex_count=3,color_count=3,
        edges=[[0,1],[1,2]]+([[0,2]]if i else []))for i in range(2)]
    write(directory/'corpus.json',dict(protocol=PROTOCOL,generator={},tasks=tasks));bindings=[];rows=[]
    for seed in range(1,5):
        for arm in ('sequential16','independent4'):
            code='# authored synthetic source; never executed\ndef solve(n,k,e): pass\n'
            p=directory/f'selected-s{seed}-{arm}.py';p.write_text(code);code_sha=r.sha(p)
            bindings.append(dict(seed=seed,arm=arm,host=f'Spark_{seed:02d}',code_sha256=code_sha))
            for task in tasks:
                identity=dict(seed=seed,arm=arm,host=f'Spark_{seed:02d}',task_id=task['id'],
                    graph_sha256=graph_digest(task),code_sha256=code_sha)
                job_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                output={'assignment':[0,1,2]if seed!=4 else[0,0,0]};proof=verify_assignment(task,output)
                payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[3,3,task['edges']],kwargs={})],timeout=10),allow_nan=False)
                grade=dict(status='passed'if proof['solved']else'failed',solved=proof['solved'],
                    proof=proof,candidate_output=output,input_unchanged=True,cleanup_ok=True,
                    provenance='candidate',grading_authority='outer_parent',oracle_sent_to_child=False,
                    graph_sha256=graph_digest(task),child_payload_sha256=hashlib.sha256(payload.encode()).hexdigest())
                rows.append(dict(identity,job_id=job_id,infrastructure=False,solved=grade['solved'],report=grade))
    write(directory/'bindings.json',bindings)
    (directory/'grades.jsonl').write_text(''.join(json.dumps(row)+'\n'for row in rows))
    source=root/'bound.py';source.write_text('# SYNTHETIC')
    plan=root/'PROGRAM_CONFIRMATION_SELECTION.json';write(plan,dict(dataset_sha256=r.sha(directory/'corpus.json')))
    meta=dict(complete=True,verified=True,incomplete=False,completed_jobs=16,planned_jobs=16,missing_jobs=0,
        faults=[],completed_utc='2026-11-16T00:00:00Z',source_before={str(source):r.sha(source)},
        source_after={str(source):r.sha(source)},source_changed_during_run=False,
        runner_source=dict(revision='SYNTHETIC',tracked_clean=True,source_files_tracked=True),model_calls=0,
        final_idle_health=[dict(idle=True,healthy=True)for _ in range(4)],
        bindings_sha256=r.sha(directory/'bindings.json'),corpus_sha256=r.sha(directory/'corpus.json'),
        dataset_sha256=r.sha(directory/'corpus.json'),upstream_plan_sha256=r.sha(plan))
    meta['runner_source_after']=copy.deepcopy(meta['runner_source']);write(directory/'metadata.json',meta)
    write(directory/'summary.json',dict(arms={arm:dict(planned_jobs=8,recorded_jobs=8,
        known_solved=sum(row['solved']for row in rows if row['arm']==arm),
        known_unsolved=sum(not row['solved']for row in rows if row['arm']==arm),unknown_outcomes=0)
        for arm in ('sequential16','independent4')}))
    audit=root/'audit.json';refresh(directory,audit)
    return directory,audit,r.sha(plan)


def refresh(directory,audit):
    write(audit,dict(verified=True,complete=True,completed_jobs=16,input_sha256={str(directory/n):r.sha(directory/n)
        for n in ('metadata.json','summary.json','grades.jsonl','bindings.json','corpus.json')}))


class ConfirmationReportTests(unittest.TestCase):
    def test_plan_only_never_reads_outcomes_or_writes(self):
        with patch.object(r,'validate')as validate,patch.object(r,'program_report')as original, \
                contextlib.redirect_stdout(io.StringIO())as output:
            self.assertEqual(r.main(['/path/does-not-exist']),0)
            self.assertEqual(json.loads(output.getvalue())['model_calls'],0)
            validate.assert_not_called();original.assert_not_called()

    def test_valid_complete_grid_keeps_legal_negative_outcomes(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);directory,audit,pin=fixture(root)
            with patch.object(r,'HERE',root),patch.object(r,'PLAN_SHA',pin):
                meta,bindings,rows,files=r.validate(directory,audit,2)
            self.assertEqual((len(bindings),len(rows)),(8,16))
            self.assertEqual(sum(x['solved']for x in rows),12)
            self.assertEqual(sum(not x['solved']for x in rows),4)

    def test_incomplete_audit_source_and_exact_grade_corruptions_fail_closed(self):
        for case in ('incomplete','audit','source','duplicate','missing_INF','payload','false_positive','false_negative','cleanup','summary','corpus'):
            with self.subTest(case=case),tempfile.TemporaryDirectory()as d:
                root=Path(d);directory,audit,pin=fixture(root)
                if case=='incomplete':
                    meta=r.read(directory/'metadata.json');meta['complete']=False;write(directory/'metadata.json',meta)
                elif case=='source':(root/'bound.py').write_text('# CHANGED')
                elif case=='summary':
                    summary=r.read(directory/'summary.json');summary['arms']['sequential16']['known_solved']+=1;write(directory/'summary.json',summary)
                elif case=='corpus':
                    corpus=r.read(directory/'corpus.json');corpus['tasks'][0]['edges']=[];write(directory/'corpus.json',corpus)
                elif case not in ('audit',):
                    rows=[json.loads(x)for x in(directory/'grades.jsonl').read_text().splitlines()]
                    if case=='duplicate':rows[-1]=rows[0]
                    elif case=='missing_INF':rows[0].pop('infrastructure')
                    elif case=='payload':rows[0]['report']['child_payload_sha256']='forged'
                    elif case=='false_positive':rows[-1]['solved']=rows[-1]['report']['solved']=True;rows[-1]['report']['status']='passed'
                    elif case=='false_negative':rows[0]['solved']=rows[0]['report']['solved']=False;rows[0]['report']['status']='failed'
                    elif case=='cleanup':rows[0]['report']['cleanup_ok']=False
                    (directory/'grades.jsonl').write_text(''.join(json.dumps(x)+'\n'for x in rows))
                refresh(directory,audit)
                if case=='audit':
                    receipt=r.read(audit);receipt['verified']=False;write(audit,receipt)
                with patch.object(r,'HERE',root),patch.object(r,'PLAN_SHA',pin),self.assertRaises((ValueError,RuntimeError)):
                    r.validate(directory,audit,2)


if __name__=='__main__':unittest.main()
