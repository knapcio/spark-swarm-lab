"""Authored arithmetic/transport fixtures only; no model, SSH or candidate execution."""
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction as F
import hashlib,io,itertools,json,threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import harness as h
from direct_solver import build_prompt,run_direct
import followup72 as f

PLAN={'moves':[{'i':0,'j':1,'op':'+'}]}

class Recorder:
    def __init__(self):self.rows=[];self.lock=threading.Lock()
    def emit(self,kind,**fields):
        json.dumps(fields)
        with self.lock:self.rows.append(dict(type=kind,**fields))

def engine(client,target=5):
    events=client.events;e=SimpleNamespace(client=client,events=events,args=SimpleNamespace(target=target,rounds=5,seed=1,allow_fractions=False));count=itertools.count()
    def node(state,parent,depth,puzzle,agent):
        name='node-'+str(next(count));events.emit('node',node_id=name,parent_id=parent,depth=depth,state=h.canonical(state),puzzle_id=puzzle,agent_id=agent);return name
    e.node=node;return e

class FakeClient:
    def __init__(self,parsed=None,finish='length',reasoning='own notes',received=True,label='own',barrier=None):
        self.budget=h.Budget(2,8192);self.events=Recorder();self.calls=[];self.first=(parsed,finish,reasoning,received);self.label=label;self.barrier=barrier
    def call(self,agent,stage,prompt,*,thinking,max_tokens,return_meta,**context):
        self.assertions=(return_meta,thinking,max_tokens);self.calls.append(dict(stage=stage,prompt=prompt,thinking=thinking,max_tokens=max_tokens,context=context))
        if not self.budget.reserve(max_tokens):return None,dict(request_id='not-dispatched',request_dispatched=False,error='budget_exhausted')
        self.budget.settle(max_tokens,max_tokens)
        if stage=='plan':
            if self.barrier:self.barrier.wait(timeout=2)
            parsed,finish,reasoning,received=self.first
        else:parsed,finish,reasoning,received=PLAN,'stop',None,True
        return parsed,dict(request_id=self.label+'-'+stage,request_dispatched=True,finish_reason=finish,reasoning=reasoning,response_received=received)

class SolverTests(unittest.TestCase):
    def test_literal_compiler_exhaustive_small_states_and_no_operand_repair(self):
        for n in (2,3):
            for state in itertools.product(range(1,4),repeat=n):
                for a,b,op in itertools.product(range(1,5),range(1,5),('+','-','*','/')):
                    available=list(state)
                    if a not in available:expected=None
                    else:
                        i=available.index(a);available[i]=None;j=next((k for k,x in enumerate(available)if x==b),None);expected=None if j is None else dict(i=i,j=j,op=op)
                    if expected is None:
                        with self.assertRaises(h.InvalidMove):f.compile_value_move(state,dict(a=a,b=b,op=op))
                    else:
                        compiled=f.compile_value_move(state,dict(a=a,b=b,op=op));self.assertEqual(compiled,expected)
                        try:answer=h.apply_action(state,expected)
                        except h.InvalidMove:
                            with self.assertRaises(h.InvalidMove):h.apply_action(state,compiled)
                        else:self.assertEqual(h.apply_action(state,compiled),answer)
        for bad in ({'a':True,'b':2,'op':'+'},{'a':2.0,'b':2,'op':'+'},{'a':2,'b':2,'op':'+','hint':3}):
            with self.assertRaises(h.InvalidMove):f.compile_value_move((2,2),bad)
        with self.assertRaises(h.InvalidMove):h.apply_action((1,150),f.compile_value_move((1,150),dict(a=1,b=150,op='-')))

    def test_prompt_factors_and_exact_original_golden(self):
        e=engine(FakeClient());state=tuple(map(F,(2,3,7)))
        golden="Target 5. Current indexed numbers: {0: '2', 1: '3', 2: '7'}. Give one complete plan to reach the target using any subset of numbers. Each move consumes two different indexed numbers and appends their result; remaining numbers keep their order and are reindexed from zero. Use +,-,*,/. Every intermediate result must be positive integer. Use at most 2 moves. Return only a JSON object with key moves, an array of objects with integer indices i,j and single-character operator op."
        self.assertEqual(f.prompt_for(e,state,'index_original'),golden);self.assertEqual(build_prompt(e,state),golden)
        value=f.prompt_for(e,state,'value_original');self.assertNotIn('indexed numbers',value);self.assertNotIn('reindexed',value);self.assertIn("Current numbers: ['2', '3', '7']",value);self.assertIn('integer operand values a,b',value)
        self.assertTrue(f.prompt_for(e,state,'index_explicit').startswith(golden));self.assertTrue(f.prompt_for(e,state,'value_explicit').startswith(value));self.assertIn('a op b literally in that order',f.prompt_for(e,state,'value_explicit'))

    def test_trigger_is_exact_none_length_received_and_nonempty_own_reasoning(self):
        for parsed,finish,reasoning,received,eligible in [(None,'length','notes',True,True),({},'length','notes',True,False),({'moves':[]},'length','notes',True,False),(None,'stop','notes',True,False),(None,'length','notes',False,False),(None,'length','',True,False),(None,'length','   ',True,False),(None,'length',None,True,False)]:
            with self.subTest(parsed=parsed,finish=finish,reasoning=reasoning,received=received):
                c=FakeClient(parsed,finish,reasoning,received);result=f.run_followup(engine(c),tuple(map(F,(2,3,7))),'p','scribe_full');self.assertEqual(len(c.calls),2 if eligible else 1);self.assertEqual(result['scribe_triggered'],eligible);self.assertEqual(c.budget.snapshot()['completion_tokens_reserved'],0)
                if eligible:self.assertTrue(result['solved']);self.assertEqual(c.budget.tokens,8192)

    def test_full_tail_empty_lineage_and_no_cross_case_notes(self):
        notes='α'*4500+'END';results={}
        for mode in ('full','tail','empty'):
            c=FakeClient(reasoning=notes);result=f.run_followup(engine(c),(F(2),F(3),F(7)),'p','scribe_'+mode);selected=notes if mode=='full'else notes[-4096:]if mode=='tail'else'';call=c.calls[1]
            self.assertEqual(result['parent_request_id'],'own-plan');self.assertEqual(result['full_reasoning_sha256'],f.sha(notes));self.assertEqual(result['selected_notes_sha256'],f.sha(selected));self.assertEqual(result['note_char_length'],len(selected));self.assertEqual(call['max_tokens'],256);self.assertFalse(call['thinking']);self.assertEqual(c.calls[0]['max_tokens'],7936)
            self.assertEqual(call['prompt'],c.calls[0]['prompt']+f.COMMIT+(f.NOTES+selected if selected else''));results[mode]=result
        barrier=threading.Barrier(2);clients=[FakeClient(reasoning='NOTES_A',label='A',barrier=barrier),FakeClient(reasoning='NOTES_B',label='B',barrier=barrier)]
        with ThreadPoolExecutor(2)as pool:list(pool.map(lambda c:f.run_followup(engine(c),(F(2),F(3),F(7)),'p','scribe_full'),clients))
        self.assertIn('NOTES_A',clients[0].calls[1]['prompt']);self.assertNotIn('NOTES_B',clients[0].calls[1]['prompt']);self.assertNotIn('NOTES_A',clients[1].calls[1]['prompt'])

    def test_original_output_and_value_replay_leave_leftovers_and_unsolvable_unsolved(self):
        class Plain:
            def call(self,*args,**kwargs):return PLAN
        plain=Plain();plain.events=Recorder();old=run_direct(engine(plain),(F(2),F(3),F(7)),'p')
        c=FakeClient(PLAN,'stop',None);new=f.run_followup(engine(c),(F(2),F(3),F(7)),'p','index_original')
        self.assertEqual({k:new[k]for k in old},old);self.assertEqual(new['final_state'],['7','5'])
        c=FakeClient({'moves':[dict(a=2,b=3,op='+')]},'stop',None);self.assertTrue(f.run_followup(engine(c),(F(2),F(3),F(7)),'p','value_explicit')['solved'])
        c=FakeClient({'moves':[dict(a=1,b=1,op='+')]},'stop',None);self.assertFalse(f.run_followup(engine(c,target=3),(F(1),F(1)),'p','value_original')['solved'])

if __name__=='__main__':unittest.main()
