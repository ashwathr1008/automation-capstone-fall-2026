"""Integration of the real HTTP/MCP adapters with durable scientific operations.

No live model requests, account access, or external network is required.
"""
import http.client
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer

from lanm_platform import economics
from lanm_platform.core import Store
from lanm_platform.mcp import definitions, dispatch
from lanm_platform.methods import Registry
from lanm_platform.server import Application, handler_for


def method_manifest():
    return {
        "name": "Collected-product purity", "description": "Target mass fraction in a collected product sample",
        "boundary": "One measured collected fraction; no claim about whole-feed recovery",
        "assumptions": ["Input masses use the same elemental-mass basis"],
        "inputs": {"target_mass_kg": {"unit": "kg", "description": "Target mass in product"},
                   "total_product_mass_kg": {"unit": "kg", "description": "Total elemental metal mass in product"}},
        "references": ["Independent mass-fraction definition"],
        "reference_cases": [{"name": "Two kilograms in eight kilograms", "inputs": {"target_mass_kg": 2, "total_product_mass_kg": 8},
                             "expected": {"purity_fraction": .25}, "basis": "Hand calculation: 2 / 8 = 0.25"},
                            {"name": "Pure collected target", "inputs": {"target_mass_kg": 1, "total_product_mass_kg": 1},
                             "expected": {"purity_fraction": 1}, "basis": "Hand calculation: 1 / 1 = 1"}],
    }


METHOD_CODE = '''def calculate(inputs):
    target = inputs["target_mass_kg"]
    total = inputs["total_product_mass_kg"]
    if total <= 0 or target < 0 or target > total:
        raise ValueError("Masses must be nonnegative and target cannot exceed total product")
    return {"purity_fraction": target / total}
'''


class MCPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.registry = Registry(self.temp.name)
        self.project = dispatch(self.store, self.registry, "create_project", {"name": "MCP test", "target": "Nd", "competitor": "La"})
        self.pid = self.project["id"]

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, arguments=None, build=False):
        return dispatch(self.store, self.registry, name, arguments or {}, build)

    def test_mcp_keyword_dispatch_updates_and_recalculates(self):
        before = self.call("calculate_economics", {"project_id": self.pid})
        self.call("update_assumptions", {"project_id": self.pid, "values": {"usable_lifetime_cycles": 200}, "reason": "Explicit hypothetical reuse change"})
        after = self.call("calculate_economics", {"project_id": self.pid})
        state = self.call("project_state", {"project_id": self.pid})
        self.assertEqual(state["assumptions"]["usable_lifetime_cycles"], 200)
        self.assertLess(after["summary"]["cost_usd_per_kg"], before["summary"]["cost_usd_per_kg"])
        saved = self.call("list_runs", {"project_id": self.pid})
        self.assertFalse(saved[0]["stale"])
        self.assertTrue(saved[1]["stale"])
        found = self.call("search_candidates", {"project_id": self.pid, "query": "o-36", "pool": "untested", "limit": 100})
        self.assertIn("o-36", [r["id"] for r in found["candidates"]])
        details = self.call("candidate_details", {"project_id": self.pid, "candidate_id": "o-36"})
        self.assertEqual(len(details["screening"]["mean"]), 15)
        self.assertEqual(details["experiments"], [])

    def test_build_check_register_execute_is_reusable_after_restart(self):
        with self.assertRaisesRegex(ValueError, "active mode"):
            self.call("save_method_draft", {"method_id": "product-purity", "manifest": method_manifest(), "code": METHOD_CODE})
        self.call("save_method_draft", {"method_id": "product-purity", "manifest": method_manifest(), "code": METHOD_CODE}, build=True)
        with self.assertRaises(ValueError):
            self.call("run_method", {"project_id": self.pid, "method_id": "product-purity", "inputs": {"target_mass_kg": 3, "total_product_mass_kg": 4}})
        checks = self.call("check_method", {"method_id": "product-purity"}, build=True)
        self.assertTrue(checks["passed"])
        registered = self.call("register_method", {"method_id": "product-purity"}, build=True)
        inputs = {"target_mass_kg": 3, "total_product_mass_kg": 4}
        result = self.call("run_method", {"project_id": self.pid, "method_id": registered["id"], "inputs": inputs})
        self.assertEqual(result["outputs"], {"purity_fraction": .75})
        self.assertEqual(result["inputs"], inputs)
        restart = Store(self.temp.name)
        self.assertEqual(restart.get_run(self.pid, result["id"])["method_version"], registered["version"])
        replay = dispatch(restart, Registry(self.temp.name), "run_method", {"project_id": self.pid, "method_id": registered["id"], "inputs": inputs})
        self.assertEqual(replay["outputs"], result["outputs"])
        self.assertEqual(replay["boundary"], result["boundary"])

    def test_saved_builtin_identifier_resolves_to_same_method(self):
        calculation = self.call("calculate_economics", {"project_id": self.pid})
        method = self.call("read_method", {"method_id": calculation["method_id"]})
        self.assertEqual(method["version"], calculation["method_version"])
        inputs = method.get("inputs", method.get("input_schema", {}))
        self.assertIn("collected_target_kg_per_l_cycle", inputs)
        self.assertEqual(inputs["collected_target_kg_per_l_cycle"]["unit"], "kg/L/cycle")

    def test_registered_version_cannot_silently_change_implementation(self):
        self.call("save_method_draft", {"method_id": "product-purity", "manifest": method_manifest(), "code": METHOD_CODE}, build=True)
        self.call("check_method", {"method_id": "product-purity"}, build=True)
        registered = self.call("register_method", {"method_id": "product-purity"}, build=True)
        method_path = Path(registered["path"]) / "method.py"
        method_path.write_text(METHOD_CODE.replace("target / total", "0"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity|changed|digest|version|check"):
            self.call("run_method", {"project_id": self.pid, "method_id": registered["id"],
                                      "inputs": {"target_mass_kg": 3, "total_product_mass_kg": 4}})

    def test_seed_scientific_contexts_are_not_only_screening(self):
        names = {tool["name"] for tool in definitions()}
        self.assertIn("library_evidence", names)
        evidence = self.call("library_evidence", {"candidate_id": "o-36"})
        self.assertIn("published_o36_pr_la_agarose", [r["id"] for r in evidence["contexts"]])
        self.assertTrue(any(r["context_id"] == "published_o36_pr_la_agarose" for r in evidence["assertions"]))
        candidate = self.call("candidate_details", {"candidate_id": "o-36", "project_id": self.pid})
        self.assertEqual(candidate["accepted_experiment_count"], 0)

    def test_mcp_sensitivity_saves_scenarios_without_revising_inputs(self):
        before = self.call("project_state", {"project_id": self.pid})
        result = self.call("sensitivity", {"project_id": self.pid, "keys": ["usable_lifetime_cycles"], "factors": [.5, 1, 2]})
        after = self.call("project_state", {"project_id": self.pid})
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["assumptions"], after["assumptions"])
        self.assertEqual(result["kind"], "sensitivity")
        rows = result["sensitivity"][0]["rows"]
        self.assertGreater(rows[0]["cost_usd_per_kg"], rows[-1]["cost_usd_per_kg"])
        self.assertEqual(self.call("list_runs", {"project_id": self.pid})[0]["id"], result["id"])

    def test_stdio_jsonrpc_protocol_and_store_reads(self):
        import lanm_platform.mcp as adapter
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_state", "arguments": {"project_id": self.pid}}},
        ]
        completed = subprocess.run([sys.executable, str(Path(adapter.__file__)), "--data", self.temp.name],
                                   input="\n".join(json.dumps(r) for r in requests) + "\n", text=True,
                                   capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        replies = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        names = {row["name"] for row in replies[1]["result"]["tools"]}
        self.assertNotIn("save_method_draft", names)
        state = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(state["id"], self.pid)


class HTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.pid = self.app.store.list_projects()[0]["id"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.app.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        payload = json.dumps(body) if body is not None else None
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    def test_http_scientific_update_requires_explicit_accept_and_matched_context(self):
        conditions = {"target": "Nd", "support": "agarose", "feed": "defined nitrate mixture"}
        status, configured = self.request("POST", f"/api/projects/{self.pid}", {"changes": {"configuration": conditions}, "reason": "Define the next experiment"})
        self.assertEqual(status, 200)
        self.assertEqual(configured["configuration"]["support"], "agarose")
        status, _ = self.request("POST", f"/api/projects/{self.pid}/assumptions", {"values": {"cost_ceiling_usd_per_kg": 10000000}, "reason": "Separate scientific completeness from allowance in test fixture"})
        self.assertEqual(status, 200)
        status, draft = self.request("POST", f"/api/projects/{self.pid}/experiments", {
            "candidate_id": "o-36", "label": "Processed fixture", "conditions": conditions,
            "metrics": {"collected_target_kg_per_l_cycle": .001, "cycle_time_hours": 4,
                        "purity_fraction": .99, "recovery_fraction": .9, "cycles_observed": 5},
            "notes": "Integration fixture; not an actual lab result"})
        self.assertEqual(status, 201)
        status, rank = self.request("POST", f"/api/projects/{self.pid}/rank", {"pool": "updated"})
        self.assertEqual((status, rank["pool_count"]), (200, 0))
        status, accepted = self.request("POST", f"/api/experiments/{draft['id']}/accept", {"reason": "Explicit fixture acceptance"})
        self.assertEqual((status, accepted["status"]), (200, "accepted"))
        status, rank = self.request("POST", f"/api/projects/{self.pid}/rank", {"pool": "updated"})
        self.assertEqual((status, rank["eligible_count"]), (200, 1))
        self.assertEqual(rank["rows"][0]["candidate_id"], "o-36")
        status, calculation = self.request("POST", f"/api/projects/{self.pid}/calculate", {"candidate_id": "o-36"})
        self.assertEqual(status, 200)
        self.assertEqual(calculation["assumptions"]["cycle_time_hours"], 4)
        self.assertEqual(calculation["assumptions"]["usable_lifetime_cycles"], 100)
        status, candidates = self.request("GET", f"/api/candidates?project_id={self.pid}&pool=untested")
        self.assertEqual((status, candidates["total"]), (200, 615))

    def test_http_invalid_changes_leave_evidence_and_revisions_unchanged(self):
        before = self.app.store.get_project(self.pid)
        status, result = self.request("POST", f"/api/projects/{self.pid}/assumptions", {"values": {"usable_lifetime_cycles": -1}, "reason": "Invalid input"})
        self.assertEqual(status, 400)
        self.assertIn("error", result)
        after = self.app.store.get_project(self.pid)
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["assumptions"], after["assumptions"])
        status, result = self.request("GET", "/api/projects", headers={"Origin": "https://unrelated.example"})
        self.assertEqual(status, 403)

    def test_http_custom_method_execution_saves_exact_inputs(self):
        self.app.registry.create_draft("product-purity", method_manifest(), METHOD_CODE)
        status, checks = self.request("POST", "/api/methods/product-purity/check", {})
        self.assertEqual((status, checks["passed"]), (200, True))
        status, registered = self.request("POST", "/api/methods/product-purity/register", {})
        self.assertEqual(status, 200)
        status, result = self.request("POST", f"/api/projects/{self.pid}/calculate", {
            "method_id": registered["id"], "inputs": {"target_mass_kg": 7, "total_product_mass_kg": 10}})
        self.assertEqual(status, 200)
        self.assertEqual(result["outputs"]["purity_fraction"], .7)
        status, history = self.request("GET", f"/api/projects/{self.pid}/runs")
        self.assertEqual(status, 200)
        self.assertEqual(history["runs"][0]["inputs"], {"target_mass_kg": 7, "total_product_mass_kg": 10})
        self.assertEqual(history["runs"][0]["method_version"], registered["version"])

    def test_citation_preview_serves_verified_pdf_inline_and_downloads_only_explicitly(self):
        content=b"%PDF-1.4\nEvidence fixture\n%%EOF"
        metadata={"id":"preview-fixture","title":"Fixture paper","url":"https://example.org/paper.pdf",
                  "path":"Week_1/paper.pdf","sha256":hashlib.sha256(content).hexdigest()}
        with self.app.store._connect() as db:
            db.execute("INSERT INTO library_records VALUES(?,?,?)",("sources:preview-fixture","sources",json.dumps(metadata)))
        archive=self.app.data_dir/"legacy"/"weeks1-3.zip"
        archive.parent.mkdir()
        with zipfile.ZipFile(archive,"w") as package: package.writestr(metadata["path"],content)
        status,preview=self.request("GET",f"/api/projects/{self.pid}/evidence-preview?url=https%3A%2F%2Fexample.org%2Fpaper.pdf")
        self.assertEqual((status,preview["preview_kind"]),(200,"pdf"))
        self.assertTrue(preview["hash_verified"])
        def read(path,headers=None):
            connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=10)
            connection.request("GET",path,headers=headers or {})
            response=connection.getresponse()
            result=response.status,dict(response.getheaders()),response.read()
            connection.close()
            return result
        status,headers,body=read(preview["file_url"])
        self.assertEqual((status,body),(200,content))
        self.assertTrue(headers["Content-Disposition"].startswith("inline;"))
        self.assertIn("frame-ancestors 'self'",headers["Content-Security-Policy"])
        status,headers,body=read(preview["file_url"],{"Range":"bytes=0-4"})
        self.assertEqual((status,body),(206,b"%PDF-"))
        self.assertEqual(headers["Content-Range"],f"bytes 0-4/{len(content)}")
        self.assertEqual(read(preview["file_url"],{"Range":"bytes=999-"})[0],416)
        status,headers,body=read(preview["file_url"]+"?download=1")
        self.assertEqual((status,body),(200,content))
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))

    def test_unknown_citation_opens_an_explanation_without_a_file_response(self):
        status,result=self.request("GET",f"/api/projects/{self.pid}/evidence-preview?url=https%3A%2F%2Fexample.org%2Funsaved.pdf")
        self.assertEqual(status,200)
        self.assertFalse(result["available"])
        self.assertEqual(result["preview_kind"],"unavailable")
        self.assertNotIn("file_url",result)
        self.assertIn("reason",result)


if __name__ == "__main__":
    unittest.main()
