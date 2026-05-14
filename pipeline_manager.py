"""RunPod handler shim for AIBO pipeline access."""

from __future__ import annotations

import os
from importlib import import_module


class PipelineManager:
  def __init__(self, model_path: str | None = None, device: str = "cuda"):
    if model_path:
      os.environ["MODEL_PATH"] = model_path

    cfg_mod = import_module("01_config")
    pipe_mod = import_module("04_pipeline_manager")

    self.sys_cfg = cfg_mod.SystemConfig()
    self._manager = pipe_mod.FluxA100PipelineManager(self.sys_cfg)
    if not self._manager.build():
      raise RuntimeError("Pipeline build failed")

  def get_pipeline(self):
    return self._manager.pipe_base
