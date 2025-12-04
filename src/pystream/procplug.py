import os
import json
import types
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ProcSpec:
    name: str
    module: str
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    path: Optional[str] = None

class ProcessorPipeline:
    """
    Lightweight plugin runner for image frames.

    - Modules live under `processors_dir` (default from JSON)
    - Each module defines: `process(img, meta=None, **params)` -> img OR (img, meta)
    - Pipeline order & params are configured via JSON
    - Optional hot-reload of modules on file change
    """
    def __init__(self, processors_dir: str, specs: List[ProcSpec], hot_reload: bool = True):
        self.processors_dir = processors_dir
        self.specs = specs
        self.hot_reload = hot_reload
        self._mods: Dict[str, types.ModuleType] = {}
        self._mtimes: Dict[str, float] = {}
        self._load_all()

    @classmethod
    def from_config(cls, config_path: str) -> "ProcessorPipeline":
        with open(config_path, "r") as f:
            cfg = json.load(f)
        processors_dir = cfg.get("processors_dir", "processors")
        pipeline_cfg = cfg.get("pipeline", [])
        specs: List[ProcSpec] = []
        for p in pipeline_cfg:
            specs.append(ProcSpec(
                name=p.get("name", p["module"]),
                module=p["module"],
                enabled=p.get("enabled", True),
                params=p.get("params", {}),
                path=None
            ))
        hot_reload = bool(cfg.get("hot_reload", True))
        return cls(processors_dir, specs, hot_reload=hot_reload)

    def _module_path(self, module: str) -> str:
        if module.endswith(".py"):
            return module if os.path.isabs(module) else os.path.join(self.processors_dir, module)
        return os.path.join(self.processors_dir, module + ".py")

    def _load_module(self, path: str):
        if not os.path.exists(path):
            return None
        name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod

    def _load_all(self):
        for spec in self.specs:
            path = self._module_path(spec.module)
            spec.path = path
            mod = self._load_module(path)
            if mod is not None:
                self._mods[spec.name] = mod
                self._mtimes[path] = os.path.getmtime(path)

    def _maybe_reload(self, spec: ProcSpec):
        if not self.hot_reload or not spec.path:
            return
        try:
            mtime = os.path.getmtime(spec.path)
        except FileNotFoundError:
            return
        last = self._mtimes.get(spec.path)
        if last is None or mtime <= last:
            return
        mod = self._load_module(spec.path)
        if mod is not None:
            self._mods[spec.name] = mod
            self._mtimes[spec.path] = mtime

    def apply(self, img, meta: Optional[Dict[str, Any]] = None):
        """Apply the configured pipeline in order."""
        if meta is None:
            meta = {}
        for spec in self.specs:
            if not spec.enabled:
                continue
            self._maybe_reload(spec)
            mod = self._mods.get(spec.name)
            if mod is None or not hasattr(mod, "process"):
                continue
            out = mod.process(img, meta=meta, **(spec.params or {}))
            if isinstance(out, tuple) and len(out) == 2:
                img, meta = out
            else:
                img = out
        return img
