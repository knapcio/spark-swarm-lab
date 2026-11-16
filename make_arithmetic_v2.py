#!/usr/bin/env python3
"""Plan-first arithmetic-v2 construction. History scan/generation need frozen plan and owner idle GO."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from fractions import Fraction
import hashlib,json,random,re
from pathlib import Path
from harness import apply_action
from make_tasks import RULES,key,moves,one_step

HERE=Path(__file__).resolve().parent
PLAN='ARITHMETIC_V2_CORPUS_PLAN.json'
SEED=2026111601
PROTOCOL='synthetic-countdown-v2'
def require(ok,message):
    if not ok:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def encoded(value):return (json.dumps(value,indent=2)+'\n').encode()

def generate(seed,excluded,development=16,evaluation=48):
    """Exact v1 RNG/construction/filter order; counts alone are parameterized."""
    require(type(seed)is int and seed>0,'Positive integer seed required')
    require(all(type(n)is int and n>0 and n%2==0 for n in (development,evaluation)),'Positive even split counts required')
    rng,used,tasks,witnesses,attempts=random.Random(seed),set(excluded),[],{},0
    for split,count in (('development',development),('evaluation',evaluation)):
        for index in range(count):
            size=4 if index%2==0 else 6
            for _ in range(20000):
                attempts+=1
                numbers=[rng.randint(1,10)for _ in range(size-2)]+rng.sample([25,50,75,100],2)
                rng.shuffle(numbers)
                state,actions=tuple(map(Fraction,numbers)),[]
                for _ in range(rng.randint(2,size-1)):
                    options=[(a,c)for a,c in moves(state)if c[-1]<=1000000]
                    action,state=rng.choice(options);actions.append(action)
                target=int(state[-1]);digest=key(numbers,target)
                if not 10<=target<=999 or target in numbers or digest in used or one_step(numbers,target):continue
                used.add(digest);task_id=f'{split[:3]}-{digest[:12]}'
                tasks.append(dict(id=task_id,split=split,numbers=numbers,target=target))
                witnesses[task_id]=dict(actions=actions,witness_length=len(actions),final_state=list(map(str,state)))
                break
            else:raise RuntimeError('Generation attempt limit reached; no output written')
    return tasks,witnesses,attempts

def verify(tasks,witnesses,excluded,development=16,evaluation=48):
    require(len(tasks)==len({t['id']for t in tasks})==len({key(t['numbers'],t['target'])for t in tasks})==development+evaluation,'Task counts/identities/fingerprints')
    require(Counter((t['split'],len(t['numbers']))for t in tasks)=={('development',4):development//2,('development',6):development//2,('evaluation',4):evaluation//2,('evaluation',6):evaluation//2},'Balanced4/6 split grid')
    require(set(witnesses)=={t['id']for t in tasks},'Witness grid differs')
    for task in tasks:
        numbers,target=task['numbers'],task['target'];require(all(type(n)is int and n>0 for n in numbers)and type(target)is int and 10<=target<=999,'Positive integer task domain')
        require(key(numbers,target)not in excluded and target not in numbers and not one_step(numbers,target),'Excluded/initial/one-step task')
        witness=witnesses[task['id']];require(2<=len(witness['actions'])<=len(numbers)-1 and witness['witness_length']==len(witness['actions']),'Construction path length')
        state=tuple(map(Fraction,numbers))
        for action in witness['actions']:state=apply_action(state,action)
        require(target in state and list(map(str,state))==witness['final_state'],'Construction witness does not replay')

def collect(obj,found):
    """Initial task/config objects only; never parse model text or execute source."""
    if isinstance(obj,dict):
        if 'target'in obj and ('numbers'in obj or 'state'in obj):
            try:
                state=tuple(Fraction(str(n))for n in obj.get('numbers',obj.get('state')));target=Fraction(str(obj['target']))
                if 2<=len(state)<=6 and all(n>0 and n.denominator==1 for n in state)and target.denominator==1 and target>0:found.add(key(state,int(target)))
            except (ValueError,TypeError,ZeroDivisionError):pass
        for name,value in obj.items():
            if name=='puzzle'and isinstance(value,str):
                try:numbers,target=value.split(':');collect(dict(numbers=numbers.split(','),target=target),found)
                except ValueError:pass
            if name in ('puzzle_fingerprints','excluded_prior_fingerprints')and isinstance(value,list):found.update(x for x in value if isinstance(x,str)and re.fullmatch('[0-9a-f]{64}',x))
            if name=='command'and isinstance(value,list):
                for i,flag in enumerate(value[:-1]):
                    if flag in ('--puzzle','--calibration-puzzles')and isinstance(value[i+1],str):
                        for puzzle in value[i+1].split(';'):collect({'puzzle':puzzle},found)
            if name=='puzzle_witnesses'and isinstance(value,dict):
                for puzzle in value:collect({'puzzle':puzzle},found)
            collect(value,found)
    elif isinstance(obj,list):
        for value in obj:collect(value,found)

def inventory(root,plan):
    paths=sorted({p for pattern in plan['exclusion_allowlist']for p in root.glob(pattern)if p.is_file()or p.is_symlink()})
    require(all(p.resolve().is_relative_to(root.resolve())and not any(q.is_symlink()for q in (p,*p.parents)if q.is_relative_to(root))for p in paths),'Symlink in exclusion scope; review before proceeding')
    require(all(not re.search(r'credential|auth[-_.]?status|cookie|password|secret|\.env($|\.)',p.name,re.I)for p in paths),'Restricted filename in exclusion scope')
    return {str(p.relative_to(root)):sha(p)for p in paths}

def exclusion_scan(root,plan,plan_sha):
    files=inventory(root,plan);found=set()
    for name in files:
        path=root/name
        if path.suffix=='.jsonl':objects=[o for line in path.read_bytes().splitlines()if line.strip()if(o:=json.loads(line)).get('type')in ('run_start','puzzle_start')]
        else:objects=[read(path)]  # Include generator/planned outputs regardless of protocol.
        for obj in objects:collect(obj,found)
    for puzzle in plan['historical_initial_puzzles']:collect({'puzzle':puzzle},found)
    require(inventory(root,plan)==files,'History changed during exclusion scan')
    return dict(complete_exclusion_scan=True,plan_sha256=plan_sha,inventory=files,fingerprints=sorted(found),historical_initial_puzzles=plan['historical_initial_puzzles'],generated_utc=datetime.now(timezone.utc).isoformat())

def gate(plan,admission):
    require(plan.get('status')=='FROZEN'and plan.get('seed')==SEED and plan.get('counts')=={'development':16,'evaluation':48}and plan.get('source_sha256'),'Prospective plan/source freeze required')
    require({'make_arithmetic_v2.py','test_make_arithmetic_v2.py','make_tasks.py','harness.py'}<=set(plan['source_sha256']),'Complete trusted generator/source pin set required')
    receipt=read(admission)
    require(all(receipt.get(k)is True for k in ('verified','all_model_timing_idle','root_go','prospective_plan_frozen'))and receipt.get('plan_sha256')==sha(HERE/PLAN),'Explicit hash-bound idle RootGO required')
    require(isinstance(receipt.get('verified_utc'),str),'RootGO verified_utc string required')
    stamp=datetime.fromisoformat(receipt['verified_utc'].replace('Z','+00:00'))
    require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds()==0,'RootGO verified_utc must be UTC')
    require(0<=(datetime.now(timezone.utc)-stamp).total_seconds()<=900,'RootGO must be current, not future, and at most900seconds old')
    require(all(sha(HERE/n)==h for n,h in plan['source_sha256'].items()),'Generator/trusted source changed')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group();group.add_argument('--scan-exclusions',action='store_true');group.add_argument('--run',action='store_true');p.add_argument('--admission',type=Path);p.add_argument('--exclusion-scan',type=Path,default=HERE/'.runtime/ARITHMETIC_V2_EXCLUSION_SCAN.json');p.add_argument('--output',type=Path);args=p.parse_args(argv)
    if not args.run and not args.scan_exclusions:print(json.dumps(dict(mode='plan',seed=SEED,counts={'development':16,'evaluation':48},history_scanned=False,tasks_generated=0,required='Frozen plan, complete exclusion scan and explicit all-model-timing-idle RootGO')));return 0
    require(args.admission is not None,'Owner admission required');plan=read(HERE/PLAN);gate(plan,args.admission);plan_sha=sha(HERE/PLAN)
    if args.scan_exclusions:
        require(not args.exclusion_scan.exists()and args.exclusion_scan.parent.resolve()==(HERE/'.runtime').resolve(),'New top-level runtime exclusion inventory required');scan=exclusion_scan(HERE,plan,plan_sha)
        with args.exclusion_scan.open('xb')as stream:stream.write(encoded(scan))
        print(json.dumps(dict(mode='exclusions_written',files=len(scan['inventory']),fingerprints=len(scan['fingerprints']))));return 0
    require(args.output is not None and not args.output.exists(),'New output directory required');scan=read(args.exclusion_scan)
    require(scan.get('complete_exclusion_scan')is True and scan.get('plan_sha256')==plan_sha and scan.get('historical_initial_puzzles')==plan['historical_initial_puzzles']and scan['inventory']==inventory(HERE,plan),'Complete unchanged exclusion inventory required')
    tasks,witnesses,attempts=generate(SEED,scan['fingerprints']);verify(tasks,witnesses,set(scan['fingerprints']))
    require(scan['inventory']==inventory(HERE,plan),'History changed during construction; rescan required')
    common=dict(protocol=PROTOCOL,generator_seed=SEED,rules=RULES,generation_attempts=attempts,construction='Exact make_tasks.generate process with16/48 counts; same filtering/distribution procedure, not matched minimum-depth or hardness.',plan_sha256=plan_sha,exclusion_scan_sha256=sha(args.exclusion_scan),excluded_prior_fingerprints=scan['fingerprints'],exclusion_manifest=scan['inventory'],source_sha256=plan['source_sha256'])
    public=dict(common,tasks=tasks);private=dict(common,witnesses=witnesses,note='Private construction paths only. Never load this file in a model worker. Paths prove existence, not minimum depth.')
    args.output.mkdir(parents=True,exist_ok=False)
    for name,value in [('tasks.json',public),('reference-witnesses.json',private)]:
        with(args.output/name).open('xb')as stream:stream.write(encoded(value))
    print(json.dumps(dict(mode='generated',tasks=64,verified=True,output=str(args.output))));return 0

if __name__=='__main__':raise SystemExit(main())
