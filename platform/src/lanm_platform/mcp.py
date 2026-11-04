"""Standard stdio MCP adapter over the platform's scientific operations."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None,""}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lanm_platform.core import Store
from lanm_platform.methods import Registry
from lanm_platform import guidance

def schema(properties=None,required=None):
    return {"type":"object","properties":properties or {},"required":required or [],"additionalProperties":False}

S={"type":"string"}
N={"type":"number"}
O={"type":"object"}

def definitions(allow_build=False):
    specs=[
        ("project_state","Read this project's current assumptions, revisions, configuration and saved status. Call before changing inputs.",{"project_id":S},["project_id"]),
        ("list_projects","List durable research projects.",{},[]),
        ("create_project","Create a separate scientific scenario for a target REE and competitor.",{"name":S,"target":S,"competitor":S,"description":S},["name","target","competitor"]),
        ("update_project","Update project description or configuration (support/feed). Use only when user asks; give a reason.",{"project_id":S,"changes":O,"reason":S},["project_id","changes","reason"]),
        ("update_assumptions","Persist explicitly requested assumption changes. Values are numeric and use canonical keys/units from project_state. Prior versions remain retained. Candidate overrides require candidate_id.",{"project_id":S,"values":O,"reason":S,"candidate_id":S},["project_id","values","reason"]),
        ("search_candidates","Search library metadata and screen profiles. Pools are all, untested or updated. Untested is project-relative accepted experiments.",{"project_id":S,"query":S,"pool":{"type":"string","enum":["all","untested","updated"]},"limit":{"type":"integer","minimum":1,"maximum":100}},["project_id"]),
        ("candidate_details","Read exact candidate screening observations and project experiments; screening signal is not process capacity or selectivity.",{"candidate_id":S,"project_id":S},["candidate_id","project_id"]),
        ("prioritize_candidates","Evaluate and save the entire eligible pool before limiting displayed rows. Untested priorities use published screening contrast; updated priorities require accepted applicable results. Optional assumption_overrides and configuration_overrides simulate a scenario without committing project inputs; give scenario_reason. exclude_candidate_ids removes explicitly requested candidates. Save the returned run ID for later selection/export. Useful lifetime does not affect untested screening scores.",{"project_id":S,"pool":{"type":"string","enum":["untested","updated"]},"limit":{"type":"integer","minimum":1,"maximum":30},"assumption_overrides":O,"configuration_overrides":O,"exclude_candidate_ids":{"type":"array","items":S,"uniqueItems":True},"scenario_reason":S},["project_id","pool"]),
        ("save_testing_selection","Save the user's exact ordered shortlist from a ranking snapshot for a later CSV. Supply 1-8 distinct eligible candidate IDs and a reason, including requested substitutions or reordering. Does not change project assumptions or experiments. Old project revisions require deliberate allow_stale=true; otherwise rerank using the intended scenario.",{"project_id":S,"ranking_run_id":S,"candidate_ids":{"type":"array","items":S,"minItems":1,"maxItems":8,"uniqueItems":True},"reason":S,"allow_stale":{"type":"boolean"}},["project_id","ranking_run_id","candidate_ids","reason"]),
        ("list_testing_selections","List saved ordered testing selections in this project so a later 'export those candidates' can recover the intended snapshot.",{"project_id":S},["project_id"]),
        ("get_testing_selection","Read an exact saved testing selection, its ranking/scenario and project-change status.",{"project_id":S,"selection_id":S},["project_id","selection_id"]),
        ("create_testing_batch","Create a saved CSV batch for serial-dilution MVP testing. count MUST be user-chosen 1-8; assigns A1-H1. Values are stock-solution dispense volumes in uL before water addition. Omitting both volume settings uses random whole-number 35-250 uL inclusive. For a custom subset, supply both bounds within 35-250 uL; ask for a missing bound. Every starting well receives the same fixed water volume, configured by the receiving automation, which also checks stock plus water against the selected plate's working-volume limit. Values are simulated and saved unchanged on re-download. Use selection_id for the agreed conversational shortlist, or ranking_run_id for an exact committed/hypothetical ranking; never supply both. With neither, ranks current project using pool (default untested). Shortages fail. Returns download_url: give that link to the user. Does not run automation or accept experiments. allow_stale=true only for deliberately requested historical snapshots.",{"project_id":S,"count":{"type":"integer","minimum":1,"maximum":8},"stock_volume_min_ul":{"type":"number","minimum":35,"maximum":250,"description":"Minimum stock-solution volume in uL. Supply with stock_volume_max_ul."},"stock_volume_max_ul":{"type":"number","minimum":35,"maximum":250,"description":"Maximum stock-solution volume in uL. Supply with stock_volume_min_ul."},"ranking_run_id":S,"selection_id":S,"pool":{"type":"string","enum":["untested","updated"]},"seed":{"type":"integer","minimum":0},"allow_stale":{"type":"boolean"}},["project_id","count"]),
        ("list_testing_batches","List saved testing batches and their CSV download links. Saved stock volumes and candidate assignments remain unchanged; legacy concentration batches retain their original units.",{"project_id":S},["project_id"]),
        ("get_testing_batch","Read a saved batch's exact candidates, stock volumes, fixed-water policy, plate wells, selection/scenario provenance and CSV download URL. Legacy concentration batches retain their original schema and units.",{"project_id":S,"batch_id":S},["project_id","batch_id"]),
        ("calculate_economics","Run and save the built-in simplified separation-unit economic model using exact project/candidate assumptions. Returns cost breakdown, applicability, break-even lifetime and conditional status.",{"project_id":S,"candidate_id":S},["project_id"]),
        ("add_scale_prediction","Save an explicitly user-supplied larger-column scenario, never inferred protein behavior. Required values: collected_target_kg_per_l_cycle, cycle_time_hours, usable_lifetime_cycles, target_production_kg_per_day, equipment_cost_usd, labor_hours_per_day, labor_rate_usd_per_hour. Ask for missing predictions and revised scale costs; never fabricate them. Other economic values snapshot shared assumptions. Optional purity/recovery/feed values must be explicitly supplied. No accepted measurements or candidate overrides transfer automatically; no project inputs or experiment pools change. Intended bed volume is TOTAL aggregate operating material. Describe support/feed/flow and prediction basis.",{"project_id":S,"label":S,"intended_bed_volume_l":N,"scale_description":S,"basis":S,"values":O,"candidate_id":S,"source_url":S},["project_id","label","intended_bed_volume_l","scale_description","basis","values"]),
        ("list_scale_predictions","List saved researcher-supplied scale predictions; these are not accepted measurements.",{"project_id":S},["project_id"]),
        ("get_scale_prediction","Read a scale prediction's immutable input snapshot, supplied values, inherited assumptions and basis.",{"project_id":S,"prediction_id":S},["project_id","prediction_id"]),
        ("calculate_scale_prediction","Calculate and save economics from the exact saved prediction snapshot. Compares required aggregate bed volume with intended volume and flags disagreement; does not predict hydrodynamics or protein performance.",{"project_id":S,"prediction_id":S},["project_id","prediction_id"]),
        ("sensitivity","Save a hypothetical sensitivity sweep of declared input factors around current economics. It does not overwrite assumptions or measurements, and is not a confidence interval.",{"project_id":S,"candidate_id":S,"keys":{"type":"array","items":S},"factors":{"type":"array","items":N}},["project_id"]),
        ("add_experiment","Create a DRAFT processed experiment. Do not fabricate measurements or automatically accept. Conditions must state target/support/feed; numeric metrics retain their names and units.",{"project_id":S,"candidate_id":S,"label":S,"conditions":O,"metrics":O,"notes":S},["project_id","candidate_id","label","conditions","metrics"]),
        ("accept_experiment","Accept a previously drafted experiment only when the user explicitly asks to accept it. This changes pool membership; explain context checks.",{"experiment_id":S,"reason":S},["experiment_id","reason"]),
        ("list_sources","List archived source evidence linked to the project.",{"project_id":S},["project_id"]),
        ("list_guidance","List the compact LanM handbook catalog, or find relevant section summaries. Original synthesis requiring scientific review; inspect primary evidence for claims.",{"query":S},[]),
        ("read_guidance","Read one LanM handbook section with its source links and review status. This is interpretive guidance, not experimental evidence.",{"section_id":S},["section_id"]),
        ("search_pubmed","Search NCBI PubMed and archive returned citations and abstracts in this project. No full text retrieved, no experimental acceptance or assumption changes. PubMed does not cover all REE engineering literature. Use focused public scientific terms.",{"project_id":S,"query":S,"limit":{"type":"integer","minimum":1,"maximum":20},"sort":{"type":"string","enum":["relevance","date"]}},["project_id","query"]),
        ("fetch_pubmed","Retrieve and archive up to 20 known PubMed IDs as citations and abstracts. Published literature remains distinct from accepted project measurements.",{"project_id":S,"pmids":{"type":"array","items":S,"minItems":1,"maxItems":20}},["project_id","pmids"]),
        ("list_literature_searches","Read this project's latest 20 saved PubMed searches and source references.",{"project_id":S},["project_id"]),
        ("read_source","Read a bounded, hash-verified source excerpt from project text or the original archived literature. Query finds a term with surrounding context. Missing text is reported explicitly.",{"project_id":S,"source_id":S,"query":S,"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":20000}},["project_id","source_id"]),
        ("library_evidence","Read retained published scientific contexts, assertions and formula references, optionally for one candidate. These records are literature evidence, not accepted project experiments.",{"candidate_id":S},[]),
        ("save_source","Archive an actual source excerpt with title and URL. Literature does not become a team experiment. Preserve conflicting claims rather than overwrite.",{"project_id":S,"title":S,"text":S,"url":S},["project_id","title","text"]),
        ("list_runs","List saved calculations and their input/model versions.",{"project_id":S},["project_id"]),
        ("get_run","Read an exact project-owned saved ranking or calculation with its assumptions and scenario. Use the original run ID when continuing a hypothetical scenario.",{"project_id":S,"run_id":S},["project_id","run_id"]),
        ("list_methods","List available built-in, draft, and registered analysis methods.",{},[]),
        ("read_method","Read method source, boundary, assumptions, input schema and checks.",{"method_id":S},["method_id"]),
        ("run_method","Apply an explicitly registered method@version with inputs, saving the result to this project.",{"project_id":S,"method_id":S,"inputs":O},["project_id","method_id","inputs"]),
    ]
    if allow_build:
        specs += [
            ("save_method_draft","Create/update a reusable numerical Python tool. Code defines calculate(inputs), returns a JSON dict; supports math/statistics, arithmetic, bounded loops and helper functions. No filesystem/network or private attributes. Manifest needs name,description,boundary,assumptions,inputs (key -> unit/default/description),references,reference_cases (inputs,expected,basis). Independent reference expected values are required. Preserve legacy model independently; do not copy REEPS source.",{"method_id":S,"manifest":O,"code":S},["method_id","manifest","code"]),
            ("check_method","Run independent declared reference cases in a separate process with timeout. Passing checks does not validate scientific assumptions.",{"method_id":S},["method_id"]),
            ("register_method","Register a version whose current reference checks passed. This makes it reusable in Analysis; it is not a claim of industrial validation.",{"method_id":S},["method_id"]),
        ]
    readonly={"project_state","list_projects","search_candidates","candidate_details","list_sources","read_source","library_evidence","list_runs","get_run","list_methods","read_method","list_guidance","read_guidance","list_literature_searches","list_scale_predictions","get_scale_prediction","list_testing_selections","get_testing_selection","list_testing_batches","get_testing_batch"}
    return [{"name":name,"description":desc,"inputSchema":schema(props,req),
             "annotations":{"readOnlyHint":name in readonly,"destructiveHint":False,"openWorldHint":name in {"search_pubmed","fetch_pubmed"}}}
            for name,desc,props,req in specs]

def dispatch(store,registry,name,args,allow_build=False):
    permitted={x["name"] for x in definitions(allow_build)}
    if name not in permitted: raise ValueError("This tool is not available in the active mode")
    mappings={"project_state":"get_project","search_candidates":"list_candidates","candidate_details":"get_candidate","prioritize_candidates":"rank","calculate_economics":"calculate","save_source":"add_source"}
    if name=="project_state": return store.get_project(args["project_id"])
    if name=="list_guidance": return guidance.select(args["query"]) if args.get("query") else guidance.catalog()
    if name=="read_guidance": return guidance.read(args["section_id"])
    if name=="list_methods": return registry.list()
    if name=="read_method": return registry.get(args["method_id"])
    if name=="save_method_draft": return registry.create_draft(**args)
    if name=="check_method": return registry.check(args["method_id"])
    if name=="register_method": return registry.register(args["method_id"])
    if name=="run_method":
        result=registry.run(args["method_id"],dict(args["inputs"]))
        return store.save_custom_run(args["project_id"],result)
    return getattr(store,mappings.get(name,name))(**args)

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",required=True)
    parser.add_argument("--allow-build",action="store_true")
    args=parser.parse_args()
    store,registry=Store(Path(args.data)),Registry(Path(args.data))
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if "id" not in request: continue
            method=request.get("method")
            if method=="initialize":
                result={"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"lanm-research","version":"0.1.0"}}
            elif method=="tools/list": result={"tools":definitions(args.allow_build)}
            elif method=="ping": result={}
            elif method=="tools/call":
                params=request["params"]
                try:
                    value=dispatch(store,registry,params["name"],params.get("arguments",{}),args.allow_build)
                    result={"content":[{"type":"text","text":json.dumps(value,ensure_ascii=False,allow_nan=False)}],"isError":False}
                except Exception as exc:
                    result={"content":[{"type":"text","text":str(exc)}],"isError":True}
            else:
                print(json.dumps({"jsonrpc":"2.0","id":request["id"],"error":{"code":-32601,"message":"Unknown method"}}),flush=True)
                continue
            print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result},ensure_ascii=False),flush=True)
        except Exception as exc:
            print(json.dumps({"jsonrpc":"2.0","id":locals().get("request",{}).get("id"),"error":{"code":-32603,"message":str(exc)}}),flush=True)

if __name__=="__main__": main()
