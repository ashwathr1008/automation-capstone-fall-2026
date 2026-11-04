"""Optional live integration checks. Uses the signed-in Codex account only when run explicitly."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from lanm_platform.runtime import Rpc,Runtime
from lanm_platform.core import Store

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--probe",action="store_true")
    parser.add_argument("--mode",default="research")
    parser.add_argument("--message",default="Briefly explain what our current economic model includes and excludes. Do not change anything.")
    args=parser.parse_args()
    if args.probe:
        client=Rpc(args.data,args.mode)
        try:
            client.start()
            account=client.request("account/read",{})
            models=client.request("model/list",{"limit":20})
            print(json.dumps({"connected":True,"signed_in":bool(account.get("account")),"models":[m.get("model") for m in models.get("data",[])]}),flush=True)
        finally: client.close()
        return
    store=Store(args.data)
    projects=store.list_projects()
    project=projects[0] if projects else store.create_project("Live integration check","Nd","La","Isolated runtime check; not laboratory evidence.")
    runtime=Runtime(store,args.data)
    cursor=0
    try:
        job=runtime.submit(project["id"],args.message,args.mode)
        while not job.done:
            with job.condition: job.condition.wait(timeout=1)
            batch=job.events[cursor:]
            cursor+=len(batch)
            for event in batch:
                print(json.dumps(event,ensure_ascii=False),flush=True)
        time.sleep(.5)
        print(json.dumps({"saved_messages":len(store.messages(project["id"])),"elapsed":round(time.monotonic()-job.created,2)}),flush=True)
    finally: runtime.close()

if __name__=="__main__": main()
