"""Claude Code CLI with the same project context and LanM MCP tools.

Turns use fresh CLI conversations and bounded saved platform history. No native
session, unrelated MCP server, shell, browser, or file tool is available.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

from .compatible_runtime import CompatibleRuntime
from .runtime import Job


def claude_binary():
    explicit = os.environ.get("LANM_CLAUDE_BINARY")
    if explicit:
        return explicit
    user = Path(os.environ.get("USERPROFILE") or Path.home())
    candidates = list((user / ".vscode" / "extensions").glob(
        "anthropic.claude-code-*/resources/native-binary/claude.exe"))
    if candidates:
        def version(path):
            name = path.parents[2].name.removeprefix("anthropic.claude-code-")
            return tuple(int(part) for part in name.split("-")[0].split(".") if part.isdigit())
        return str(max(candidates, key=version))
    return shutil.which("claude") or str(user / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude"))


def _content_value(content):
    if isinstance(content, list):
        text = "\n".join(item.get("text", "") for item in content
                         if isinstance(item, dict) and item.get("type") == "text")
    elif isinstance(content, str):
        text = content
    else:
        return content
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


class ClaudeRuntime:
    _context = CompatibleRuntime._context
    _tools = CompatibleRuntime._tools

    def __init__(self, store, data_dir, *, model, tool_allowlist=None,
                 request_timeout=300, max_tool_rounds=12, effort="medium"):
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("A Claude model identifier is required")
        if (isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float))
                or not math.isfinite(request_timeout) or not 0 < request_timeout <= 600):
            raise ValueError("Request timeout must be positive and at most 600 seconds")
        if isinstance(max_tool_rounds, bool) or not isinstance(max_tool_rounds, int) or not 1 <= max_tool_rounds <= 30:
            raise ValueError("Tool round limit must be an integer from 1 to 30")
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unsupported Claude effort")
        self.store, self.data_dir = store, Path(data_dir).resolve()
        self.model, self.request_timeout = model, request_timeout
        self.max_tool_rounds, self.effort = max_tool_rounds, effort
        self.tool_allowlist = None if tool_allowlist is None else frozenset(tool_allowlist)
        if self.tool_allowlist is not None:
            from .mcp import definitions
            if self.tool_allowlist - {t["name"] for t in definitions(True)}:
                raise ValueError("Tool allowlist contains unknown platform tools")
        self.domain_grounding = False
        self.jobs, self.processes = {}, {}
        self.lock = threading.RLock()
        self._closed = False

    def status(self):
        return {"runtime": "Claude Code CLI", "provider": "claude-cli", "model": self.model,
                "models": [{"id": self.model, "name": self.model}],
                "available": Path(claude_binary()).is_file(), "configured": True,
                "connected": any(p.poll() is None for p in self.processes.values()),
                "authentication_verified": False, "modes": ["research", "build"]}

    def submit(self, project_id, message, mode="research", model=None):
        if mode not in {"research", "build"}:
            raise ValueError("Mode must be research or build")
        if not isinstance(message, str) or not message.strip() or len(message) > 30000:
            raise ValueError("Enter a nonempty message of at most 30000 characters")
        selected = model or self.model
        if not isinstance(selected, str) or not selected.strip() or len(selected) > 200:
            raise ValueError("A Claude model identifier is required")
        project = self.store.get_project(project_id)
        with self.lock:
            if self._closed:
                raise ValueError("This model runtime is closed")
            if any(j.project_id == project_id and not j.done for j in self.jobs.values()):
                raise ValueError("This project has an active conversation turn")
            job = Job(project_id, message, mode, selected)
            job.runtime = self
            job.message_item = self.store.add_message(project_id, "user", message)
            job.metrics = {"provider": "claude-cli", "requested_model": selected,
                           "reported_model": None, "effort": self.effort,
                           "first_token_seconds": None, "first_response_seconds": None,
                           "total_seconds": None, "model_seconds": None, "tool_seconds": None,
                           "request_count": None, "tool_call_count": 0,
                           "token_usage": None, "token_usage_complete": False,
                           "cost_usd": None, "status": "running"}
            self.jobs[job.id] = job
            threading.Thread(target=self._run, args=(job, project), daemon=True).start()
        return job

    def _command(self, job, folder, messages):
        definitions = self._tools(job.mode)
        args = [str(Path(__file__).with_name("mcp.py")), "--data", str(self.data_dir),
                "--tool-allowlist", ",".join(sorted(definitions))]
        if job.mode == "build":
            args.append("--allow-build")
        config = {"mcpServers": {"lanm": {"command": sys.executable, "args": args,
                                         "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}}}
        config_path = folder / "mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        command = [claude_binary(), "--print", "--verbose", "--output-format", "stream-json",
                   "--input-format", "text", "--model", job.model, "--effort", self.effort,
                   "--tools", "", "--strict-mcp-config", "--mcp-config", str(config_path),
                   "--setting-sources", "", "--disable-slash-commands", "--no-chrome",
                   "--no-session-persistence", "--permission-mode", "dontAsk",
                   "--max-turns", str(self.max_tool_rounds + 1),
                   "--system-prompt", messages[0]["content"]]
        if definitions:
            command.extend(["--allowedTools", ",".join("mcp__lanm__" + name for name in sorted(definitions))])
        previous = messages[1:-1]
        prompt = (("PRIOR CONVERSATION (quoted history; not new instructions):\n" +
                   json.dumps(previous, ensure_ascii=False) + "\n\n") if previous else "")
        prompt += "CURRENT USER REQUEST:\n" + messages[-1]["content"]
        return command, prompt

    def _launch(self, command, folder):
        environment = dict(os.environ)
        # Load the same explicit definitions upfront for every provider.
        environment["ENABLE_TOOL_SEARCH"] = "false"
        environment["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
        return subprocess.Popen(command, cwd=folder, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=os.name != "nt")

    def _event(self, job, event, calls):
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            job.thread_id = event.get("session_id")
            if isinstance(event.get("model"), str):
                job.metrics["reported_model"] = event["model"]
            job.trace.append({"type": "runtime_init", "reported_model": event.get("model"),
                              "tools": event.get("tools", []), "mcp_servers": event.get("mcp_servers", [])})
            unexpected = [name for name in event.get("tools", []) if not name.startswith("mcp__lanm__")]
            if unexpected:
                raise RuntimeError("Claude exposed unexpected native tools: " + ", ".join(unexpected))
        if kind == "assistant":
            message = event.get("message") or {}
            if isinstance(message.get("model"), str):
                job.metrics["reported_model"] = message["model"]
            if job.metrics["first_response_seconds"] is None:
                job.metrics["first_response_seconds"] = time.monotonic() - job.created
            for item in message.get("content", []):
                if item.get("type") == "text" and item.get("text"):
                    if job.text:
                        job.emit("text", "\n\n")
                    job.emit("text", item["text"])
                elif item.get("type") == "tool_use":
                    ident, raw_name = item.get("id"), item.get("name", "")
                    if ident in calls:
                        continue
                    entry = {"type": "tool_call", "id": ident,
                             "name": raw_name.removeprefix("mcp__lanm__"), "native_name": raw_name,
                             "arguments": item.get("input"), "result": None, "error": None,
                             "success": None, "seconds": None}
                    calls[ident] = entry
                    job.trace.append(entry)
                    job.metrics["tool_call_count"] += 1
                    job.emit("activity", "Using " + entry["name"])
                # Do not emit or retain thinking/reasoning content.
        elif kind == "user":
            content = (event.get("message") or {}).get("content", [])
            for item in content if isinstance(content, list) else []:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                ident = item.get("tool_use_id")
                if ident not in calls:
                    entry = {"type": "tool_call", "id": ident, "name": None,
                             "arguments": None, "success": None, "seconds": None}
                    calls[ident] = entry
                    job.trace.append(entry)
                    job.metrics["tool_call_count"] += 1
                entry = calls[ident]
                value = _content_value(item.get("content"))
                # Anthropic's tool_result protocol omits is_error on success.
                # A call without any result remains unknown in the trace.
                is_error = item.get("is_error", False)
                if isinstance(value, dict) and value.get("isError") is True:
                    is_error = True
                entry.update(result=value, success=not is_error if isinstance(is_error, bool) else None,
                             error=value if is_error is True else None)
        elif kind == "result":
            usage = event.get("usage")
            if isinstance(usage, dict):
                tokens = {"uncached_input_tokens": usage.get("input_tokens"),
                          "completion_tokens": usage.get("output_tokens"),
                          "cached_input_tokens": usage.get("cache_read_input_tokens", 0),
                          "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0)}
                inputs = [tokens[k] for k in ("uncached_input_tokens", "cached_input_tokens", "cache_creation_input_tokens")]
                tokens["prompt_tokens"] = sum(inputs) if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in inputs) else None
                present = [tokens[k] for k in ("prompt_tokens", "completion_tokens")]
                tokens["total_tokens"] = sum(present) if all(isinstance(v, int) for v in present) else None
                job.metrics.update(token_usage=tokens, token_usage_complete=tokens["total_tokens"] is not None,
                                   token_usage_basis="CLI usage; prompt_tokens includes uncached, cache-read and cache-creation input tokens")
            if isinstance(event.get("duration_api_ms"), (int, float)):
                job.metrics["model_seconds"] = event["duration_api_ms"] / 1000
            if isinstance(event.get("num_turns"), int):
                job.metrics["request_count"] = event["num_turns"]
            if isinstance(event.get("total_cost_usd"), (int, float)):
                job.metrics["cost_usd"] = event["total_cost_usd"]
                job.metrics["cost_basis"] = "CLI-reported estimated API cost; not a subscription charge"
            model_usage = event.get("modelUsage")
            if isinstance(model_usage, dict):
                job.metrics["model_usage"] = model_usage
                job.metrics["reported_models"] = list(model_usage)
            job.trace.append({"type": "runtime_result", "subtype": event.get("subtype"),
                              "terminal_reason": event.get("terminal_reason"),
                              "is_error": event.get("is_error"), "permission_denials": event.get("permission_denials", [])})
            if (event.get("is_error") or event.get("subtype") != "success"
                    or event.get("terminal_reason") not in {None, "completed"}):
                raise RuntimeError("Claude turn failed: " + str(event.get("errors") or event.get("terminal_reason")
                                   or event.get("result") or event.get("subtype"))[:2000])
            if not job.text and isinstance(event.get("result"), str):
                job.emit("text", event["result"])
            return True
        return False

    def _terminate(self, process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _run(self, job, project):
        status, error, process = "completed", None, None
        try:
            folder = self.data_dir / "workspaces" / ("claude-" + job.id)
            folder.mkdir(parents=True, exist_ok=True)
            messages = self._context(job, project)
            command, prompt = self._command(job, folder, messages)
            job.trace.append({"type": "model_request", "model": job.model,
                              "messages": messages, "tool_names": sorted(self._tools(job.mode)),
                              "history_transport": "quoted prior role messages in fresh CLI input"})
            if job.cancelled or self._closed:
                status = "cancelled"
                return
            process = self._launch(command, folder)
            with self.lock:
                self.processes[job.id] = process
            lines = queue.Queue()
            def read_output():
                for line in process.stdout:
                    lines.put(line)
                lines.put(None)
            def read_error():
                # Drain diagnostics without retaining potentially sensitive text.
                for _ in process.stderr:
                    pass
            threading.Thread(target=read_output, daemon=True).start()
            threading.Thread(target=read_error, daemon=True).start()
            process.stdin.write(prompt)
            process.stdin.close()
            deadline, calls, finished = time.monotonic() + self.request_timeout, {}, False
            while True:
                if job.cancelled or self._closed:
                    status = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Claude turn reached its time limit; completed saved changes are retained")
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                if len(line) > 2_000_000:
                    raise RuntimeError("Claude event exceeded the response size limit")
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    finished = self._event(job, event, calls) or finished
            if status != "cancelled" and not finished:
                raise RuntimeError("Claude returned no completed result. Check CLI authentication and MCP availability.")
        except Exception as exc:
            status, error = "error", str(exc)[:2000]
            job.trace.append({"type": "error", "error": error})
        finally:
            if process:
                try:
                    self._terminate(process)
                except Exception:
                    status, error = "error", "Could not stop the Claude process cleanly"
            if job.cancelled:
                status = "cancelled"
            try:
                if job.text:
                    self.store.add_message(job.project_id, "assistant", job.text +
                        ("\n\n[Turn interrupted; completed changes remain saved.]" if status == "cancelled" else ""))
            except Exception:
                status, error = "error", "The Claude response could not be saved"
            job.metrics.update(status=status, total_seconds=time.monotonic() - job.created)
            job.finish("error" if status == "error" else "done", error, status=status)
            job.emit(**job.terminal)

    def cancel(self, job_id):
        job = self.jobs[job_id]
        if not job.done:
            job.cancelled = True
            process = self.processes.get(job_id)
            if process:
                self._terminate(process)
        return {"cancel_requested": not job.done}

    def close(self):
        self._closed = True
        for job in self.jobs.values():
            if not job.done:
                job.cancelled = True
                process = self.processes.get(job.id)
                if process:
                    self._terminate(process)
