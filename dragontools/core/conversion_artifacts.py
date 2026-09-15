# -*- coding: utf-8 -*-
"""Canonical contract for conversion companion/result artifacts.

The registry owns the legacy sidecar/postprocess/failure mappings so refactors
cannot silently split their ownership. ``ConversionArtifactBundle`` is the
atomic hand-off object between converter, DV fallback, parallel coordination,
GUI bookkeeping and move preparation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class ArtifactRegistry:
    sidecar_outputs: dict[str, list[str]] = field(default_factory=dict)
    postprocess_outputs: dict[str, list[dict]] = field(default_factory=dict)
    failure_details: dict[str, dict] = field(default_factory=dict)

    def clear(self) -> None:
        self.sidecar_outputs.clear()
        self.postprocess_outputs.clear()
        self.failure_details.clear()

    def bundle(self, input_path: str, *, output_path: str = "", status: str = "") -> "ConversionArtifactBundle":
        return ConversionArtifactBundle(
            input_path=str(input_path),
            output_path=str(output_path or ""),
            sidecars=tuple(self.sidecar_outputs.get(input_path, ()) or ()),
            postprocess=tuple(dict(item) for item in (self.postprocess_outputs.get(input_path, ()) or ())),
            failure=dict(self.failure_details.get(input_path, {}) or {}),
            status=str(status or ""),
        )

    def publish(self, bundle: "ConversionArtifactBundle") -> None:
        key = bundle.input_path
        self.sidecar_outputs[key] = list(bundle.sidecars)
        self.postprocess_outputs[key] = [dict(item) for item in bundle.postprocess]
        if bundle.failure:
            self.failure_details[key] = dict(bundle.failure)
        else:
            self.failure_details.pop(key, None)


@dataclass(frozen=True, slots=True)
class ConversionArtifactBundle:
    input_path: str
    output_path: str = ""
    sidecars: tuple[str, ...] = ()
    postprocess: tuple[dict, ...] = ()
    failure: dict = field(default_factory=dict)
    status: str = ""

    @classmethod
    def from_worker(
        cls,
        worker: Any,
        input_path: str,
        *,
        output_path: str = "",
        status: str = "",
    ) -> "ConversionArtifactBundle":
        registry = registry_from_worker(worker)
        return registry.bundle(input_path, output_path=output_path, status=status)


def registry_from_worker(worker: Any) -> ArtifactRegistry:
    """Return one coherent snapshot source for refactored or legacy workers."""
    if worker is None:
        return ArtifactRegistry()
    session = getattr(worker, "_session_state", None)
    registry = getattr(session, "artifacts", None) if session is not None else None
    if isinstance(registry, ArtifactRegistry):
        return registry

    sidecars = getattr(session, "sidecar_outputs", None) if session is not None else None
    postprocess = getattr(session, "postprocess_outputs", None) if session is not None else None
    failures = getattr(session, "failure_details", None) if session is not None else None
    if not isinstance(sidecars, dict):
        candidate = getattr(worker, "_sidecar_outputs", None)
        sidecars = candidate if isinstance(candidate, dict) else {}
    if not isinstance(postprocess, dict):
        candidate = getattr(worker, "_postprocess_outputs", None)
        postprocess = candidate if isinstance(candidate, dict) else {}
    if not isinstance(failures, dict):
        candidate = getattr(worker, "_failure_details", None)
        failures = candidate if isinstance(candidate, dict) else {}
    return ArtifactRegistry(sidecars, postprocess, failures)


def publish_bundle_to_worker(worker: Any, bundle: ConversionArtifactBundle) -> None:
    """Publish an atomic child result to a worker without replacing map objects."""
    registry = registry_from_worker(worker)
    registry.publish(bundle)


def bundles_from_worker(worker: Any, paths: Iterable[str] | None = None) -> list[ConversionArtifactBundle]:
    registry = registry_from_worker(worker)
    keys = set(paths or ())
    if not keys:
        keys.update(registry.sidecar_outputs)
        keys.update(registry.postprocess_outputs)
        keys.update(registry.failure_details)
    return [registry.bundle(path) for path in sorted(keys)]
