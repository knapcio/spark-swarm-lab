"""Authored tiny graphs only; no corpus evaluation, witnesses or model calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import csp_classical as c
from csp_tasks import PROTOCOL, verify_assignment


TRIANGLE = dict(id='authored-triangle', vertex_count=3, color_count=2, edges=[[0,1],[0,2],[1,2]])
PATH = dict(id='authored-path', vertex_count=4, color_count=2, edges=[[0,1],[1,2],[2,3]])


def tiny_public(path):
    tasks=[dict(id=f'authored-{i}',split='development' if i<4 else 'evaluation',vertex_count=i+2,color_count=2,edges=[]) for i in range(16)]
    path.write_text(json.dumps(dict(protocol=PROTOCOL,generator={'scope':'authored fixture'},tasks=tasks)))


class ClassicalTests(unittest.TestCase):
    def test_random_scores_exactly_sixteen_and_counts_duplicate_work(self):
        with patch.object(c,'verify_assignment',wraps=verify_assignment) as verifier:
            result=c.run_control(TRIANGLE,'random_assignment',1,clock=lambda:0)
        self.assertEqual(result['fitness_evaluations'],16)
        self.assertEqual(result['fitness_edge_constraint_checks'],48)
        self.assertEqual(result['fitness_vertex_domain_checks'],48)
        self.assertEqual(result['final_verifier_calls'],1)
        self.assertEqual(verifier.call_count,17)
        self.assertFalse(result['solved'])
        self.assertEqual(result['model_calls'],0)

    def test_genetic_reuses_unchanged_existing_algorithm_and_exact_cap(self):
        result=c.run_control(TRIANGLE,'genetic',2,clock=lambda:0)
        expected=c.classical_search(TRIANGLE,2,generations=128,population_size=32)
        self.assertEqual(result['fitness_evaluations'],3616)
        self.assertEqual(result['fitness_evaluations'],expected['evaluations'])
        self.assertEqual(result['best_assignment'],expected['assignment'])
        self.assertEqual(result['verification']['conflicts'],expected['conflicts'])
        self.assertFalse(result['solved'])

    def test_min_conflicts_counts_every_alternative_color_and_restart(self):
        with patch.object(c,'verify_assignment',wraps=verify_assignment) as verifier:
            result=c.run_control(TRIANGLE,'min_conflicts',3,clock=lambda:0)
        self.assertEqual(result['fitness_evaluations'],4*(1+1024*2))
        self.assertEqual(verifier.call_count,result['fitness_evaluations']+1)
        self.assertEqual(result['fitness_edge_constraint_checks'],result['fitness_evaluations']*3)
        self.assertFalse(result['solved'])
        self.assertEqual(result['status'],'complete')

    def test_deterministic_seeded_assignments_and_exact_success(self):
        for arm in c.PARAMETERS:
            for seed in [1,2,3]:
                with self.subTest(arm=arm,seed=seed):
                    first=c.run_control(PATH,arm,seed,clock=lambda:0)
                    second=c.run_control(PATH,arm,seed,clock=lambda:0)
                    self.assertEqual(first['best_assignment'],second['best_assignment'])
                    self.assertEqual(first['fitness_evaluations'],second['fitness_evaluations'])
                    self.assertEqual(first['solved'],second['solved'])
                    if first['solved']:
                        self.assertTrue(verify_assignment(PATH,{'assignment':first['best_assignment']})['solved'])

    def test_deadline_preserves_partial_work_without_claiming_infeasibility(self):
        ticks=iter([0,0,0,31,31])
        result=c.run_control(TRIANGLE,'random_assignment',1,clock=lambda:next(ticks))
        self.assertEqual(result['status'],'budget_exhausted')
        self.assertEqual(result['fitness_evaluations'],1)
        self.assertIsNotNone(result['best_assignment'])
        self.assertFalse(result['solved'])
        self.assertGreaterEqual(result['wall_seconds'],30)

    def test_late_zero_conflicts_does_not_become_in_budget_success(self):
        task=dict(id='authored-edgeless',vertex_count=2,color_count=2,edges=[])
        ticks=iter([0,0,31,31])
        result=c.run_control(task,'random_assignment',1,clock=lambda:next(ticks))
        self.assertTrue(result['verification']['solved'])
        self.assertFalse(result['solved'])
        self.assertIsNone(result['first_verified_solution_seconds'])
        self.assertEqual(result['status'],'budget_exhausted')

    def test_algorithm_claim_is_not_trusted_over_exact_verifier(self):
        def false_claim(task,seed,scorer):
            scorer.evaluate([0,0,0])
            return {'solved':True}
        with patch.object(c,'_genetic',side_effect=false_claim):
            result=c.run_control(TRIANGLE,'genetic',1,clock=lambda:0)
        self.assertFalse(result['solved'])
        self.assertEqual(result['verification']['conflicts'],3)

    def test_plan_only_has_all_splits_seeds_controls_and_no_witness_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tasks.json';tiny_public(path)
            original_open=Path.open
            def guarded_open(p,*args,**kwargs):
                if p.name=='reference-witnesses.json':raise AssertionError('Witness read forbidden')
                return original_open(p,*args,**kwargs)
            with patch.object(Path,'open',guarded_open),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(c.main(['--dataset',str(path),'--plan']),0)
            plan=json.loads(output.getvalue())
            self.assertEqual(len(plan['cases']),144)
            self.assertEqual(sum(x['split']=='development' for x in plan['cases']),36)
            self.assertEqual(sum(x['split']=='evaluation' for x in plan['cases']),108)
            self.assertEqual({x['seed'] for x in plan['cases']},{1,2,3})
            self.assertEqual(plan['parameters']['genetic']['max_fitness_evaluations'],3616)
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_run_gate_blocks_fitness_and_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tasks.json';tiny_public(path);output=Path(directory)/'results'
            with patch('reference_worker.verify_gate',side_effect=RuntimeError('throughput pending')),patch.object(c,'run_control') as run:
                with self.assertRaisesRegex(RuntimeError,'throughput pending'):
                    c.main(['--dataset',str(path),'--output',str(output),'--run','--gate-root',directory])
                run.assert_not_called()
            self.assertFalse(output.exists())
            output.mkdir();(output/'owned-marker').write_text('keep')
            with patch('reference_worker.verify_gate',return_value={'verified':True}),patch.object(c,'run_control') as run:
                with self.assertRaises(FileExistsError):c.main(['--dataset',str(path),'--output',str(output),'--run'])
                run.assert_not_called()
            self.assertEqual((output/'owned-marker').read_text(),'keep')

    def test_final_boundary_drift_invalidates_even_all_finished_cases(self):
        for drift in [None,'dataset','source']:
            with self.subTest(drift=drift),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'tasks.json';tiny_public(path);output=Path(directory)/'results'
                plan,tasks=c.make_plan(path);plan['cases']=plan['cases'][:1]
                sources=dict(plan['source_sha256'])
                def work(task,arm,seed):
                    if drift=='dataset':path.write_text(path.read_text()+'\n')
                    if drift=='source':sources['csp_classical.py']='changed'
                    return dict(arm=arm,seed=seed,solved=False)
                with patch.object(c,'make_plan',return_value=(plan,tasks)),patch.object(c,'source_hashes',side_effect=lambda:dict(sources)),patch.object(c,'run_control',side_effect=work),patch('reference_worker.verify_gate',return_value={'verified':True}):
                    status=c.main(['--dataset',str(path),'--output',str(output),'--run'])
                metadata=json.loads((output/'metadata.json').read_text())
                self.assertEqual(metadata['completed_cases'],metadata['planned_cases'])
                self.assertEqual(metadata['final_dataset_sha256'],c.sha(path))
                self.assertEqual(metadata['source_changed'],drift=='source')
                self.assertEqual(metadata['data_changed'],drift=='dataset')
                self.assertEqual(metadata['verified'],drift is None)
                self.assertEqual(metadata['incomplete'],drift is not None)
                self.assertEqual(status,int(drift is not None))


if __name__=='__main__':unittest.main()
