"""Compare trusted old/new baseline source on authored JSON fixtures; no HTTP."""
import ast,hashlib,json,subprocess,sys
from pathlib import Path
from fractions import Fraction
from types import ModuleType,SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];SOURCE=ROOT/'.runtime/nemotron72-followup-source'
sys.path.insert(0,str(SOURCE))
import direct_solver,harness
BASE='1a462213dd368cdfa664076399b5a458cdd1a40a'
original=subprocess.check_output(['git','show',BASE+':direct_solver.py'],cwd=SOURCE,text=True)
old=ModuleType('trusted_original_direct_solver');exec(compile(original,'trusted-git-baseline-direct_solver.py','exec'),old.__dict__)
class Recorder:
    def __init__(self):self.events=[];self.calls=[];self.serial=0
    def emit(self,event,**kwargs):self.events.append(dict(type=event,**kwargs))
    def node(self,state,parent,depth,puzzle,agent):
        self.serial+=1;identity='authored-node-'+str(self.serial);self.emit('node',state=harness.canonical(state),parent=parent,depth=depth,puzzle=puzzle,agent=agent,identity=identity);return identity
    def engine(self,answer,target):
        def call(*args,**kwargs):self.calls.append(dict(args=args,kwargs=kwargs));return answer
        return SimpleNamespace(client=SimpleNamespace(call=call),events=self,node=self.node,args=SimpleNamespace(rounds=5,target=target,seed=7,allow_fractions=False))
fixtures=[None,{},[],{'moves':[]},{'moves':[{'i':0,'j':1,'op':'+'}]},{'moves':[{'i':0,'j':0,'op':'+'}]},{'moves':[{'i':True,'j':1,'op':'+'}]},{'moves':[{'i':0,'j':1,'op':'-'}]},{'moves':[{'i':1,'j':0,'op':'/'}]},{'moves':[{'i':0,'j':1,'op':'bad'}]},{'moves':[{'i':0,'j':1,'op':'+'},{'i':99,'j':0,'op':'*'}]},{'moves':[{'i':0,'j':1,'op':'+'}],'extra':1}]
count=0
for initial,target in [((2,3,7),5),((2,3,7),21),((2,2,7),4),((1,150,7),149)]:
 for answer in fixtures:
  for revision in [None,2]:
   for feedback in ['', 'authored feedback']:
    a,b=Recorder(),Recorder();state=tuple(map(Fraction,initial));before=old.run_direct(a.engine(answer,target),state,'authored',0,feedback,revision);after=direct_solver.run_direct(b.engine(answer,target),state,'authored',0,feedback,revision)
    assert before==after and a.events==b.events and a.calls==b.calls,(initial,answer,revision,feedback)
    count+=1
print(json.dumps(dict(verified=True,baseline_revision=BASE,authored_golden_parity_fixtures=count,exact_comparisons=['return value','events including rewards and proposal identity','client args/prompt/context'],old_source_sha256=hashlib.sha256(original.encode()).hexdigest(),new_source_sha256=hashlib.sha256((SOURCE/'direct_solver.py').read_bytes()).hexdigest()),indent=2))
