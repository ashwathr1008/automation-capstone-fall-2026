"""Named inference profiles shared by the application and isolated comparisons.

Credentials are environment-variable references, never values in this file or UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time

from .config import DEFAULT_MODEL, data_directory
from .runtime import Runtime


def load_profiles(path=None):
    """Load an explicit profile list, or retain the existing Codex defaults."""
    explicit = path or os.environ.get("LANM_PROFILES_FILE")
    source = Path(explicit).expanduser() if explicit else data_directory() / "model_profiles.json"
    if source.is_file():
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        profiles = payload.get("profiles") if isinstance(payload, dict) else payload
    elif explicit:
        raise ValueError("Model profiles file does not exist")
    else:
        profiles = [{"id": "codex-default", "name": "Codex · " + DEFAULT_MODEL,
                     "backend": "codex", "model": DEFAULT_MODEL}]
        if DEFAULT_MODEL != "gpt-6-astra":
            profiles.append({"id": "codex-astra", "name": "Codex · Astra",
                             "backend": "codex", "model": "gpt-6-astra"})
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("Model profiles must be a nonempty list")
    seen = set()
    result = []
    allowed = {"id", "name", "backend", "model", "base_url", "api_key_env",
               "request_timeout", "max_tool_rounds", "description", "metadata",
               "enable_thinking", "max_output_tokens", "domain_grounding", "effort"}
    for item in profiles:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("Invalid profile fields; use api_key_env for credentials")
        profile = dict(item)
        ident = profile.get("id", "")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", ident) or ident in seen:
            raise ValueError("Profile IDs must be unique simple names")
        seen.add(ident)
        if profile.get("backend") not in {"codex", "compatible", "claude"}:
            raise ValueError("Profile backend must be codex, compatible or claude")
        if profile["backend"] != "compatible" and {"enable_thinking", "max_output_tokens", "domain_grounding"} & set(profile):
            raise ValueError("Thinking, output-budget and grounding profile fields require a compatible backend")
        if "effort" in profile and (profile["backend"] != "claude" or profile["effort"] not in {"low", "medium", "high", "xhigh", "max"}):
            raise ValueError("Effort is supported only for Claude profiles with a declared supported level")
        if not isinstance(profile.get("model"), str) or not profile["model"].strip():
            raise ValueError("Each profile needs an exact model name")
        if profile["backend"] == "compatible" and not isinstance(profile.get("base_url"), str):
            raise ValueError("Compatible profiles need a base_url")
        if profile["backend"] == "compatible":
            from .compatible_runtime import _endpoint
            _endpoint(profile["base_url"])
        key_env = profile.get("api_key_env")
        if key_env is not None and (not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env)):
            raise ValueError("api_key_env must name an environment variable")
        result.append(profile)
    return result


def runtime_factory_for(profile, tool_allowlist=None):
    """Return the same runtime constructor used by the app and evaluations."""
    def factory(store, data_dir):
        if profile["backend"] == "codex":
            return Runtime(store, data_dir, tool_allowlist=tool_allowlist)
        if profile["backend"] == "claude":
            from .claude_runtime import ClaudeRuntime
            return ClaudeRuntime(store, data_dir, model=profile["model"], tool_allowlist=tool_allowlist,
                                 request_timeout=profile.get("request_timeout", 300),
                                 max_tool_rounds=profile.get("max_tool_rounds", 12),
                                 effort=profile.get("effort", "medium"))
        from .compatible_runtime import CompatibleRuntime
        return CompatibleRuntime(store, data_dir, base_url=profile["base_url"],
                                 model=profile["model"], api_key_env=profile.get("api_key_env"),
                                 request_timeout=profile.get("request_timeout", 180),
                                 max_tool_rounds=profile.get("max_tool_rounds", 12),
                                 tool_allowlist=tool_allowlist,
                                 enable_thinking=profile.get("enable_thinking"),
                                 max_output_tokens=profile.get("max_output_tokens"),
                                 domain_grounding=profile.get("domain_grounding", False))
    return factory


class ProfileRuntime:
    """Route the existing UI model selector to a configured inference backend."""
    def __init__(self, store, data_dir, profiles=None):
        self.store, self.data_dir = store, Path(data_dir)
        local = self.data_dir / "model_profiles.json"
        self.profiles = profiles if profiles is not None else load_profiles(
            os.environ.get("LANM_PROFILES_FILE") or (local if local.is_file() else None))
        self.default = os.environ.get("LANM_DEFAULT_PROFILE", self.profiles[0]["id"])
        if self.default not in {p["id"] for p in self.profiles}:
            raise ValueError("LANM_DEFAULT_PROFILE is not a configured profile")
        self.backends, self.jobs = {}, {}
        self.lock = threading.RLock()
        self.history_path = self.data_dir / "model_provider_history.json"
        try:
            self.last_backends = json.loads(self.history_path.read_text(encoding="utf-8"))
            if not isinstance(self.last_backends, dict):
                self.last_backends = {}
        except (OSError, ValueError):
            self.last_backends = {}

    def status(self):
        from .config import codex_binary
        import shutil
        codex_available = bool(shutil.which(codex_binary()) or Path(codex_binary()).is_file())
        models = []
        for p in self.profiles:
            available = codex_available if p["backend"] == "codex" else bool(
                not p.get("api_key_env") or os.environ.get(p["api_key_env"]))
            if p["backend"] == "claude":
                from .claude_runtime import claude_binary
                available = bool(shutil.which(claude_binary()) or Path(claude_binary()).is_file())
            models.append({"id": p["id"], "name": p.get("name", p["model"]),
                           "backend": p["backend"], "model": p["model"],
                           "configured": available})
        return {"runtime": "Configured model backends", "model": self.default,
                "models": models, "available": any(p["configured"] for p in models),
                "codex_available": codex_available,
                "connected": any(b.status().get("connected", False) for b in self.backends.values()),
                "modes": ["research", "build"],
                "availability_note": "Configured backends connect when a conversation starts; endpoint health is checked then."}

    def submit(self, project_id, message, mode="research", model=None):
        chosen = model or self.default
        profile = next((p for p in self.profiles if p["id"] == chosen), None)
        # Preserve API clients that send the previous exact Codex model value.
        if profile is None:
            profile = next((p for p in self.profiles if p["backend"] == "codex" and p["model"] == chosen), None)
        if profile is None:
            raise ValueError("Choose a configured model profile")
        with self.lock:
            if any(j.project_id == project_id and not j.done for j in self.jobs.values()):
                raise ValueError("This project has an active conversation turn. Stop it or wait before starting another.")
            for key, job in list(self.jobs.items()):
                if job.done and time.monotonic() - job.created > 3600:
                    self.jobs.pop(key, None)
            # A single Codex runtime owns its thread file and mode connections.
            backend_key = "codex" if profile["backend"] == "codex" else profile["id"]
            backend = self.backends.get(backend_key)
            if backend is None:
                backend = runtime_factory_for(profile)(self.store, self.data_dir)
                self.backends[backend_key] = backend
            history_key = project_id + ":" + mode
            if backend_key == "codex" and self.last_backends.get(history_key, "codex") != "codex":
                # Bootstrap from saved chat after a different backend contributed;
                # an old native thread cannot contain that backend's answers.
                if hasattr(backend, "reset_thread"):
                    backend.reset_thread(project_id, mode)
            if backend_key != "codex":
                # The saved chat is project-wide, including turns in either mode.
                for chat_mode in ("research", "build"):
                    self.last_backends[project_id + ":" + chat_mode] = backend_key
            else:
                self.last_backends[history_key] = backend_key
            temporary = self.history_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.last_backends), encoding="utf-8")
            temporary.replace(self.history_path)
            job = backend.submit(project_id, message, mode, model=profile["model"])
            job.profile_id = profile["id"]
            job.backend_owner = backend
            self.jobs[job.id] = job
            return job

    def cancel(self, job_id):
        return self.jobs[job_id].backend_owner.cancel(job_id)

    def close(self):
        for backend in self.backends.values():
            backend.close()
