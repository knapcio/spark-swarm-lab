from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,json,sys
app=Path(sys.argv[1]).resolve();sys.path.insert(0,str(app));import export_benchmark as ex
raw=app/'runs/evaluation-v2-primary-aggregation';out=app/'results/evaluation-v2/primary-aggregate';out.mkdir(parents=True,exist_ok=False)
cohorts=[(app/f'runs/evaluation-v2-{d}-s{s}',app/f'results/evaluation-v2/{d}-s{s}')for d in('arithmetic','coding')for s in(1,2,3)];producer=app/'.runtime/evaluation-v2-source';entries=[]
def normalize(v):
 if not Path(v).is_absolute():return v
 if v==str(raw/'verified-ledger-original.json'):return'results/evaluation-v2/primary-aggregate/verified-ledger.json'
 for start,prefix in [(raw,'results/evaluation-v2/primary-aggregate')]+[(a,str(b.relative_to(app)))for a,b in cohorts]+[(b,str(b.relative_to(app)))for a,b in cohorts]+[(producer,'.')]:
  try:suffix=Path(v).relative_to(start).as_posix()
  except ValueError:continue
  return prefix if suffix=='.'else prefix+'/'+suffix
 return v
for source in sorted(raw.rglob('*')):
 if not source.is_file():continue
 relative=source.relative_to(raw);target_relative=Path('verified-ledger.json')if relative.name=='verified-ledger-original.json'else relative;original=source.read_bytes();patches=[];exported=original
 if source.suffix=='.json':
  exported,patches=ex.transform(original,Path('metadata.json'),normalize);obj=json.loads(exported)
  def walk(value,path=()):
   if isinstance(value,dict):
    for key,child in value.items():
     if key in ex.PROTECTED:continue
     if key in('directory','source_path','path')and isinstance(child,str):
      replacement=normalize(child)
      if replacement!=child:patches.append(dict(path=list(path+(key,)),original=child,export=replacement));value[key]=replacement
     elif key=='source_variants'and isinstance(child,list):
      for i,v in enumerate(child):
       replacement=normalize(v)
       if replacement!=v:patches.append(dict(path=list(path+(key,i)),original=v,export=replacement));child[i]=replacement
     else:walk(child,path+(key,))
   elif isinstance(value,list):
    for i,child in enumerate(value):walk(child,path+(i,))
  walk(obj)
  if patches:exported=(json.dumps(obj,indent=2,ensure_ascii=False)+'\n').encode()
  restored=json.loads(exported)
  for e in reversed(patches):
   parent=restored
   for key in e['path'][:-1]:parent=parent[key]
   assert parent[e['path'][-1]]==e['export'];parent[e['path'][-1]]=e['original']
  assert json.dumps(restored,ensure_ascii=False)==json.dumps(json.loads(original),ensure_ascii=False)
 target=out/target_relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(exported)
 entries.append(dict(source=str(source),export=str(target.relative_to(app)),original_sha256=hashlib.sha256(original).hexdigest(),export_sha256=hashlib.sha256(exported).hexdigest(),original_bytes=len(original),export_bytes=len(exported),export_byte_identical=original==exported,reverse_normalization_semantic_identity=True,formatting_may_change=bool(patches),normalizations=patches))
manifest=dict(schema_version=2,curated_utc=datetime.now(timezone.utc).isoformat(),normalization_policy='Only whitelisted directory/path/source/command/interpreter values in completed primary ledger and derived analysis documents. Hash/source/model/configuration VALUES preserved; original ledger/input SHA references retained. Parsed inverse restores original values/order/types. All CSV/SVG/PNG files byte-identical.',aggregate_script_sha256=hashlib.sha256((app/'aggregate_evaluation.py').read_bytes()).hexdigest(),curator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),files=entries)
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(out/'curate.py').write_bytes(Path(__file__).read_bytes());print('Curated',len(entries),'aggregate artifacts;changed',sum(bool(e['normalizations'])for e in entries))
