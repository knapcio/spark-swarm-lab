from pathlib import Path
import hashlib,json,sys
from datetime import datetime,timezone
app=Path(sys.argv[1]).resolve();sys.path.insert(0,str(app));import export_benchmark as ex
out=app/'results/serving-v032-20261115';out.mkdir(parents=True,exist_ok=False)
names=['serving-v032-comparison','serving-repro-v1-spark02','serving-repro-v032-spark02','v032-thinking-smoke'];sources=[(app/'runs'/name,name) for name in names];producer=app/'.runtime/evaluation-infra-fixed-source'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def normalize(value):
 if not Path(value).is_absolute():return value
 for root,prefix in [(path,'results/serving-v032-20261115/'+name) for path,name in sources]+[(producer,'.')]:
  try:suffix=Path(value).relative_to(root).as_posix()
  except ValueError:continue
  return prefix if suffix=='.' else prefix+'/'+suffix
 return value
entries=[]
def export(source,relative):
 raw=source.read_bytes();exported,patches=ex.transform(raw,relative,normalize)
 # Custom schemas have no metadata.cases; source/cache normalization is explicit.
 if relative.name in ('metadata.json','canary-launch.json'):
  obj=json.loads(exported);extra=[]
  if relative.name=='metadata.json' and isinstance(obj.get('source'),str):
   value=normalize(obj['source'])
   if value!=obj['source']:extra.append(dict(path=['source'],original=obj['source'],export=value,scope='json',record=None));obj['source']=value
  if relative.name=='canary-launch.json' and obj.get('cache')=='/home/knapcio/swarm-lab/cache-v032':
   extra.append(dict(path=['cache'],original=obj['cache'],export='~/swarm-lab/cache-v032',scope='json',record=None));obj['cache']='~/swarm-lab/cache-v032'
  if extra:
   previous=json.loads(exported);restored=dict(obj)
   for e in extra:restored[e['path'][0]]=e['original']
   assert restored==previous
   exported=(json.dumps(obj,indent=2,ensure_ascii=False)+'\n').encode();patches+=extra
  # Independently invert every structured JSON edit back to original parsed values.
  restored=json.loads(exported)
  for e in reversed(patches):
   parent=restored
   for key in e['path'][:-1]:parent=parent[key]
   assert parent[e['path'][-1]]==e['export'];parent[e['path'][-1]]=e['original']
  assert restored==json.loads(raw)
 target=out/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(exported)
 entries.append(dict(source=str(source),export=str(target.relative_to(app)),original_sha256=sha(raw),export_sha256=sha(exported),original_bytes=len(raw),export_bytes=len(exported),export_byte_identical=raw==exported,reverse_normalization_semantic_identity=True,formatting_may_change=bool(patches),normalizations=patches))
for folder,name in sources:
 for path in sorted(folder.rglob('*')):
  if path.is_file():assert not path.is_symlink();export(path,Path(name)/path.relative_to(folder))
export(app/'.runtime/v032-canary-launch.json',Path('canary-launch.json'))
manifest=dict(schema_version=2,curated_utc=datetime.now(timezone.utc).isoformat(),curator_sha256=sha(Path(__file__).read_bytes()),export_benchmark_sha256=sha(Path(ex.__file__).read_bytes()),normalization_policy='Audited export_benchmark.transform for whitelisted event/metadata/summary/log paths and Python interpreter; explicit custom metadata.source→./producer-relative and receipt.cache→~/swarm-lab/cache-v032. JSON serialization may change; inverse edits preserve parsed values. Model response/reasoning/content and all other fields unchanged. No private orchestrator/source files copied.',files=entries)
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(dict(files=len(entries),changed=sum(bool(e['normalizations'])for e in entries),output=str(out))))
