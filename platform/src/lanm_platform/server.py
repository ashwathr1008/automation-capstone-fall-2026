"""Local-only HTTP application: one service, a browser UI, and durable research data."""
from __future__ import annotations
import argparse
import atexit
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import urlparse,parse_qs,unquote,quote
import webbrowser

from . import __version__
from .config import UI_DIRECTORY,data_directory
from .core import Store
from .methods import Registry,BUILTIN
from .runtime import Runtime
from .evidence import preview,read_original
from . import guidance

class Application:
    def __init__(self,data_dir):
        self.data_dir=Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.data_dir)
        self.registry=Registry(self.data_dir)
        self.runtime=Runtime(self.store,self.data_dir)
        if not self.store.list_projects():
            self.store.create_project("Lanmodulin exploration","Nd","La","Initial exploration. Shared process inputs are scenario estimates until supported by accepted experiments.")

    def close(self): self.runtime.close()

def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        server_version="LanMResearch/"+__version__
        protocol_version="HTTP/1.1"

        def log_message(self,format,*args):
            # Do not log messages, source excerpts, prompts, or credentials.
            return

        def _headers(self,status,ctype,length=None,extra=None,frameable=False):
            self.send_response(status)
            self.send_header("Content-Type",ctype)
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            ancestors="'self'" if frameable else "'none'"
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'self'; frame-ancestors "+ancestors)
            for key,value in (extra or {}).items(): self.send_header(key,value)
            if length is not None: self.send_header("Content-Length",str(length))
            self.end_headers()

        def _json(self,value,status=200):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False,default=str).encode()
            self._headers(status,"application/json; charset=utf-8",len(data))
            self.wfile.write(data)

        def _request(self):
            length=int(self.headers.get("Content-Length","0"))
            if length>2_000_000: raise ValueError("Request exceeds 2 MB")
            if length and "application/json" not in self.headers.get("Content-Type",""):
                raise ValueError("Send JSON with Content-Type application/json")
            value=json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(value,dict): raise ValueError("Expected a JSON object")
            return value

        def _origin_ok(self):
            host=self.headers.get("Host","").split(":")[0]
            if host not in {"127.0.0.1","localhost"}: return False
            origin=self.headers.get("Origin")
            return not origin or urlparse(origin).netloc==self.headers.get("Host")

        def _source_file(self,project_id,source_id,download=False):
            data,mime,filename=read_original(app.store,project_id,source_id)
            inline=mime.split(';',1)[0] in {"application/pdf","image/png","image/jpeg","image/gif","image/webp","text/plain","text/csv"}
            if not inline and not download:
                return self._json({"error":"This file type requires an explicit download; use its archived text preview."},415)
            safe_name=re.sub(r'[^A-Za-z0-9._-]', '_',filename)[:180] or 'source'
            disposition='attachment' if download else 'inline'
            headers={"Content-Disposition":f'{disposition}; filename="{safe_name}"; filename*=UTF-8\'\'{quote(filename,safe="")}',"Accept-Ranges":"bytes"}
            start,end,status=0,len(data)-1,200
            requested=self.headers.get('Range')
            if requested:
                match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
                if not match or not any(match.groups()) or not data:
                    self._headers(416,mime,0,{"Content-Range":f"bytes */{len(data)}"},frameable=True)
                    return
                first,last=match.groups()
                if first:
                    start=int(first);end=min(int(last),end) if last else end
                else:
                    start=max(0,len(data)-int(last))
                if start>end or start>=len(data):
                    self._headers(416,mime,0,{"Content-Range":f"bytes */{len(data)}"},frameable=True)
                    return
                status=206
                headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
            body=data[start:end+1]
            self._headers(status,mime,len(body),headers,frameable=True)
            self.wfile.write(body)

        def do_GET(self):
            try:
                if not self._origin_ok(): return self._json({"error":"Local same-origin requests only"},403)
                parsed=urlparse(self.path)
                path=unquote(parsed.path)
                query={k:v[0] for k,v in parse_qs(parsed.query).items()}
                parts=path.strip("/").split("/")
                if path=="/api/status":
                    return self._json({**app.runtime.status(),"version":__version__,"data_dir":str(app.data_dir),"local_only":True})
                if path=="/api/projects": return self._json({"projects":app.store.list_projects()})
                if path=="/api/guidance": return self._json({"sections":guidance.select(query["q"]) if query.get("q") else guidance.catalog()})
                if len(parts)==3 and parts[:2]==["api","guidance"]: return self._json(guidance.read(parts[2]))
                if path=="/api/library-evidence": return self._json(app.store.library_evidence(query.get("candidate_id")))
                if path=="/api/candidates":
                    result=app.store.list_candidates(query["project_id"],query.get("q",""),query.get("pool","all"),min(100,int(query.get("limit",100))))
                    return self._json(result if isinstance(result,dict) else {"candidates":result,"total":len(result)})
                if len(parts)==3 and parts[:2]==["api","candidates"]:
                    return self._json(app.store.get_candidate(parts[2],query.get("project_id")))
                if len(parts)>=3 and parts[:2]==["api","projects"]:
                    ident=parts[2]
                    if len(parts)==3: return self._json(app.store.get_project(ident))
                    if parts[3]=="messages": return self._json({"messages":app.store.messages(ident)})
                    if parts[3]=="runs": return self._json({"runs":app.store.list_runs(ident)})
                    if parts[3]=="testing-selections":
                        if len(parts)==4: return self._json({"selections":app.store.list_testing_selections(ident)})
                        if len(parts)==5: return self._json(app.store.get_testing_selection(ident,parts[4]))
                    if parts[3]=="testing-batches":
                        if len(parts)==4: return self._json({"batches":app.store.list_testing_batches(ident)})
                        if len(parts)==5: return self._json(app.store.get_testing_batch(ident,parts[4]))
                        if len(parts)==6 and parts[5]=="csv":
                            data=app.store.testing_batch_csv(ident,parts[4]).encode("utf-8")
                            filename=re.sub(r'[^A-Za-z0-9_-]', '_',parts[4])[:100]+".csv"
                            self._headers(200,"text/csv; charset=utf-8",len(data),{"Content-Disposition":f'attachment; filename="{filename}"'})
                            self.wfile.write(data)
                            return
                    if parts[3]=="literature-searches": return self._json(app.store.list_literature_searches(ident))
                    if parts[3]=="scale-predictions":
                        if len(parts)==4: return self._json({"predictions":app.store.list_scale_predictions(ident)})
                        if len(parts)==5: return self._json(app.store.get_scale_prediction(ident,parts[4]))
                    if parts[3]=="evidence-preview":
                        result=preview(app.store,ident,url=query.get("url"),source_id=query.get("source_id"))
                        if result.get("original_available") and result.get("source_id"):
                            result["file_url"]=f"/api/projects/{quote(ident,safe='')}/sources/{quote(result['source_id'],safe='')}/file"
                        return self._json(result)
                    if parts[3]=="sources":
                        if len(parts)==6 and parts[5]=="text":
                            return self._json(app.store.read_source(ident,parts[4],query.get("query",""),int(query.get("offset",0)),int(query.get("limit",12000))))
                        if len(parts)==6 and parts[5]=="file":
                            return self._source_file(ident,parts[4],query.get("download")=="1")
                        return self._json({"sources":app.store.list_sources(ident)})
                if path=="/api/methods": return self._json({"methods":app.registry.list()})
                if len(parts)==3 and parts[:2]==["api","methods"]: return self._json(app.registry.get(parts[2]))
                if len(parts)==4 and parts[:2]==["api","jobs"] and parts[3]=="events": return self._events(parts[2])
                if path.startswith("/api/"): return self._json({"error":"Not found"},404)
                ui=UI_DIRECTORY.resolve()
                file=(ui/("index.html" if path=="/" else path.lstrip("/"))).resolve()
                if not file.is_relative_to(ui) or not file.is_file(): return self._json({"error":"Not found"},404)
                data=file.read_bytes()
                ctype=mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self._headers(200,ctype+"; charset=utf-8",len(data))
                self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass
            except (ValueError,KeyError,FileNotFoundError) as exc: self._json({"error":str(exc)},400)
            except Exception as exc: self._json({"error":str(exc)},500)

        def do_POST(self): self._mutate()
        def do_PATCH(self): self._mutate()

        def _mutate(self):
            try:
                if not self._origin_ok(): return self._json({"error":"Local same-origin requests only"},403)
                parts=unquote(urlparse(self.path).path).strip("/").split("/")
                body=self._request()
                if parts==["api","projects"]:
                    return self._json(app.store.create_project(body["name"],body.get("target","Nd"),body.get("competitor","La"),body.get("description","")),201)
                if len(parts)>=3 and parts[:2]==["api","projects"]:
                    ident=parts[2]
                    if len(parts)==3:
                        return self._json(app.store.update_project(ident,body.get("changes",body.get("values",{})),body.get("reason","Project settings updated by user")))
                    operation=parts[3]
                    if operation=="shared-evidence" and len(parts)==5:
                        allowed={"record_type","record_id","candidate_id"}
                        required={"record_type","record_id"}
                        if parts[4]=="promote":
                            allowed|={"snapshot_sha256","reason","supersedes_source_id"}
                            required|={"snapshot_sha256","reason"}
                        elif parts[4]!="preview":
                            return self._json({"error":"Not found"},404)
                        if set(body)-allowed: raise ValueError("Unsupported shared evidence field")
                        if required-set(body): raise ValueError("Supply the record identity and required promotion review fields")
                        if parts[4]=="preview": return self._json(app.store.preview_shared_evidence(ident,**body))
                        return self._json(app.store.promote_shared_evidence(ident,**body),201)
                    if operation=="testing-selections" and len(parts)==4:
                        allowed={"ranking_run_id","candidate_ids","reason","allow_stale"}
                        if set(body)-allowed: raise ValueError("Unsupported testing selection field")
                        if {"ranking_run_id","candidate_ids","reason"}-set(body): raise ValueError("Supply a saved ranking, ordered candidate IDs and selection reason")
                        return self._json(app.store.save_testing_selection(ident,**body),201)
                    if operation=="testing-batches" and len(parts)==4:
                        allowed={"count","stock_volume_min_ul","stock_volume_max_ul","ranking_run_id","selection_id","pool","seed","allow_stale"}
                        if set(body)-allowed: raise ValueError("Unsupported testing batch field")
                        if "count" not in body: raise ValueError("Supply a candidate count from 1 to 8")
                        return self._json(app.store.create_testing_batch(ident,**body),201)
                    if operation=="scale-predictions":
                        if len(parts)==4: return self._json(app.store.add_scale_prediction(ident,**body),201)
                        if len(parts)==6 and parts[5]=="calculate": return self._json(app.store.calculate_scale_prediction(ident,parts[4]))
                    if operation=="pubmed" and len(parts)==5:
                        if parts[4]=="search": return self._json(app.store.search_pubmed(ident,body["query"],body.get("limit",5),body.get("sort","relevance")))
                        if parts[4]=="fetch": return self._json(app.store.fetch_pubmed(ident,body["pmids"]))
                    if operation=="assumptions":
                        return self._json(app.store.update_assumptions(ident,body["values"],body["reason"],body.get("candidate_id")))
                    if operation=="experiments":
                        return self._json(app.store.add_experiment(ident,body["candidate_id"],body["label"],body["conditions"],body["metrics"],body.get("notes","")),201)
                    if operation=="rank":
                        scenario={key:body[key] for key in ("assumption_overrides","configuration_overrides","exclude_candidate_ids","scenario_reason") if key in body}
                        return self._json(app.store.rank(ident,body.get("pool","untested"),body.get("limit",10),**scenario))
                    if operation=="sensitivity": return self._json(app.store.sensitivity(ident,body.get("candidate_id"),body.get("keys"),body.get("factors")))
                    if operation=="calculate":
                        method=body.get("method_id")
                        if method and method!=BUILTIN:
                            result=app.registry.run(method,body.get("inputs",{}))
                            return self._json(app.store.save_custom_run(ident,result))
                        return self._json(app.store.calculate(ident,body.get("candidate_id")))
                    if operation=="sources":
                        return self._json(app.store.add_source(ident,body["title"],body["text"],body.get("url","")),201)
                    if operation=="chat":
                        job=app.runtime.submit(ident,body["message"],body.get("mode","research"),body.get("model"))
                        return self._json({"job_id":job.id},202)
                if len(parts)==4 and parts[:2]==["api","experiments"] and parts[3]=="accept":
                    return self._json(app.store.accept_experiment(parts[2],body.get("reason","Explicitly accepted in the research interface")))
                if len(parts)==4 and parts[:2]==["api","jobs"] and parts[3]=="cancel": return self._json(app.runtime.cancel(parts[2]))
                if len(parts)==4 and parts[:2]==["api","methods"]:
                    if parts[3]=="check": return self._json(app.registry.check(parts[2]))
                    if parts[3]=="register": return self._json(app.registry.register(parts[2]))
                return self._json({"error":"Not found"},404)
            except (ValueError,KeyError,FileNotFoundError) as exc: self._json({"error":str(exc)},400)
            except Exception as exc: self._json({"error":str(exc)},500)

        def _events(self,job_id):
            job=app.runtime.jobs.get(job_id)
            if not job: return self._json({"error":"Unknown job; saved conversation is available in the project"},404)
            self._headers(200,"text/event-stream; charset=utf-8")
            cursor=0
            try:
                while True:
                    with job.condition:
                        if cursor>=len(job.events) and not job.done: job.condition.wait(timeout=10)
                        events=job.events[cursor:]
                        cursor=len(job.events)
                    for event in events:
                        self.wfile.write(("data: "+json.dumps(event,ensure_ascii=False)+"\n\n").encode())
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    if job.done and cursor>=len(job.events): break
            except (BrokenPipeError,ConnectionResetError): pass
            self.close_connection=True
    return Handler

def main():
    parser=argparse.ArgumentParser(description="Run the local LanM Research platform")
    parser.add_argument("--data-dir",type=Path,default=None)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--open-browser",action="store_true")
    args=parser.parse_args()
    app=Application(args.data_dir or data_directory())
    server=ThreadingHTTPServer(("127.0.0.1",args.port),handler_for(app))
    server.daemon_threads=True
    atexit.register(app.close)
    url=f"http://127.0.0.1:{server.server_port}"
    print(f"LanM Research {__version__} — {url}",flush=True)
    print(f"Research data: {app.data_dir}",flush=True)
    if args.open_browser: threading.Timer(.4,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        app.close()

if __name__=="__main__": main()
