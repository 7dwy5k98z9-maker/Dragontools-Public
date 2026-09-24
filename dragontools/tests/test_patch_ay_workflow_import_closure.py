# -*- coding: utf-8 -*-
"""Regression: the conversion workflow import graph must be complete."""
from __future__ import annotations

import importlib


def test_workflow_module_import_closure() -> None:
    modules = (
        "dragontools.worker.workflow_duration_repair",
        "dragontools.worker.workflow_engine",
        "dragontools.worker.workflow_factory",
        "dragontools.worker.workflow_geometry_validation",
        "dragontools.worker.workflow_models",
        "dragontools.worker.workflow_output_commit",
        "dragontools.worker.workflow_override_summary",
        "dragontools.worker.workflow_pipeline_executor",
        "dragontools.worker.workflow_planning_service",
        "dragontools.worker.workflow_postprocess_commit",
        "dragontools.worker.workflow_services",
        "dragontools.worker.workflow_sidecar_commit",
        "dragontools.worker.workflow_verification_service",
        "dragontools.worker.hdr10plus_workflow_policy",
        "dragontools.worker.dv_workflow_pipeline_adapter",
        "dragontools.worker.converter_runtime_builder",
    )
    for module_name in modules:
        module = importlib.import_module(module_name)
        assert module is not None, module_name


def test_override_summary_symbol_is_available() -> None:
    module = importlib.import_module("dragontools.worker.workflow_override_summary")
    assert callable(module.format_override_summary)
