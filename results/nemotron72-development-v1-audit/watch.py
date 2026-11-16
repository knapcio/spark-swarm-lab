"""Read-only local poller; only runs the offline auditor on completed-case changes."""
import json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
launch=ROOT/'.runtime/NEMOTRON72_DEVELOPMENT_LAUNCH_V1.json'
if not launch.is_file():raise SystemExit('Launch receipt absent')
run=ROOT/'runs/nemotron72-development-v1';last=-1
while True:
    meta=json.loads((run/'metadata.json').read_text())
    rows=json.loads((run/'summary.json').read_text())if(run/'summary.json').exists()else[]
    final='completed_utc'in meta
    if len(rows)!=last or final:
        command=[sys.executable,'-B',str(HERE/'audit.py'),'--audit','--launch',str(launch)]+(['--final']if final else[])
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        if result.returncode:
            print(json.dumps(dict(auditor_error=result.stderr[-3000:],completed_cases=len(rows))),flush=True);raise SystemExit(result.returncode)
        print(result.stdout.strip(),flush=True);receipt=json.loads(result.stdout)
        if not receipt['verified']:raise SystemExit(2)
        last=len(rows)
        if final:break
    time.sleep(30)
