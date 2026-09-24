# -*- coding: utf-8 -*-
"""Qt-free client for a local ComfyUI service.

The client intentionally stays model/workflow agnostic. DragonTools can validate a
local ComfyUI instance, queue an API-format workflow and cancel exactly the queued
job without depending on any specific SDR->HDR custom node.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


JsonTransport = Callable[[str, str, dict[str, Any] | None, float], tuple[int, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ComfyUIResult:
    success: bool
    status: int = 0
    prompt_id: str = ""
    version: str = ""
    device: str = ""
    vram_total: int | None = None
    error: str = ""
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def normalize_comfyui_base_url(value: str | None) -> str:
    raw = str(value or "").strip() or "http://127.0.0.1:8188"
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _http_json(method: str, url: str, payload: dict[str, Any] | None, timeout_s: float) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, float(timeout_s))) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return status, {}
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("ComfyUI response must be a JSON object")
    return status, decoded


class ComfyUIClient:
    """Small model-neutral wrapper around ComfyUI's local HTTP API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        *,
        timeout_s: float = 3.0,
        transport: JsonTransport = _http_json,
    ) -> None:
        self.base_url = normalize_comfyui_base_url(base_url)
        self.timeout_s = max(0.1, float(timeout_s))
        self._transport = transport

    def health(self) -> ComfyUIResult:
        try:
            status, payload = self._transport("GET", f"{self.base_url}/system_stats", None, self.timeout_s)
        except Exception as exc:
            return ComfyUIResult(False, error="SERVICE_UNREACHABLE", message=str(exc))
        if status < 200 or status >= 300:
            return ComfyUIResult(False, status=status, error="HTTP_ERROR", message=f"ComfyUI HTTP {status}", payload=payload)
        system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
        devices = payload.get("devices") if isinstance(payload.get("devices"), list) else []
        primary = devices[0] if devices and isinstance(devices[0], dict) else {}
        return ComfyUIResult(
            True,
            status=status,
            version=str(system.get("comfyui_version") or ""),
            device=str(primary.get("name") or ""),
            vram_total=_int_or_none(primary.get("vram_total")),
            payload=payload,
        )

    def object_info(self) -> ComfyUIResult:
        """Return the installed ComfyUI node-class registry."""
        try:
            status, payload = self._transport("GET", f"{self.base_url}/object_info", None, self.timeout_s)
        except Exception as exc:
            return ComfyUIResult(False, error="OBJECT_INFO_FAILED", message=str(exc))
        if status < 200 or status >= 300:
            return ComfyUIResult(
                False, status=status, error="HTTP_ERROR",
                message=f"ComfyUI HTTP {status}", payload=payload,
            )
        return ComfyUIResult(True, status=status, payload=payload)

    def queue_workflow(
        self,
        workflow: Mapping[str, Any],
        *,
        client_id: str | None = None,
        prompt_id: str | None = None,
    ) -> ComfyUIResult:
        if not isinstance(workflow, Mapping) or not workflow:
            return ComfyUIResult(False, error="INVALID_WORKFLOW", message="ComfyUI workflow must be a non-empty JSON object.")
        request_payload: dict[str, Any] = {
            "prompt": dict(workflow),
            "client_id": client_id or str(uuid.uuid4()),
        }
        if prompt_id:
            request_payload["prompt_id"] = str(prompt_id)
        try:
            status, payload = self._transport("POST", f"{self.base_url}/prompt", request_payload, self.timeout_s)
        except Exception as exc:
            return ComfyUIResult(False, error="QUEUE_FAILED", message=str(exc))
        queued_id = str(payload.get("prompt_id") or prompt_id or "")
        if status < 200 or status >= 300 or not queued_id:
            return ComfyUIResult(
                False,
                status=status,
                error="QUEUE_REJECTED",
                message=str(payload.get("error") or f"ComfyUI HTTP {status}"),
                payload=payload,
            )
        return ComfyUIResult(True, status=status, prompt_id=queued_id, payload=payload)

    def history(self, prompt_id: str) -> ComfyUIResult:
        job_id = str(prompt_id or "").strip()
        if not job_id:
            return ComfyUIResult(False, error="PROMPT_ID_MISSING", message="prompt_id is required")
        try:
            status, payload = self._transport("GET", f"{self.base_url}/history/{job_id}", None, self.timeout_s)
        except Exception as exc:
            return ComfyUIResult(False, error="HISTORY_FAILED", message=str(exc))
        if status < 200 or status >= 300:
            return ComfyUIResult(False, status=status, prompt_id=job_id, error="HTTP_ERROR", message=f"ComfyUI HTTP {status}", payload=payload)
        return ComfyUIResult(True, status=status, prompt_id=job_id, payload=payload)

    def cancel(self, prompt_id: str) -> ComfyUIResult:
        """Cancel exactly one job using ComfyUI's job-specific cancellation API."""
        job_id = str(prompt_id or "").strip()
        if not job_id:
            return ComfyUIResult(False, error="PROMPT_ID_MISSING", message="prompt_id is required")
        try:
            status, payload = self._transport("POST", f"{self.base_url}/api/jobs/{job_id}/cancel", {}, self.timeout_s)
        except Exception as exc:
            return ComfyUIResult(False, error="CANCEL_FAILED", message=str(exc), prompt_id=job_id)
        if status < 200 or status >= 300:
            return ComfyUIResult(False, status=status, prompt_id=job_id, error="CANCEL_FAILED", message=f"ComfyUI HTTP {status}", payload=payload)
        cancelled = payload.get("cancelled")
        return ComfyUIResult(
            True,
            status=status,
            prompt_id=job_id,
            message="cancelled" if cancelled is True else "already_finished_or_unknown",
            payload=payload,
        )


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["ComfyUIClient", "ComfyUIResult", "normalize_comfyui_base_url"]
