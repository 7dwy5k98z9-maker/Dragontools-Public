# -*- coding: utf-8 -*-
"""Verarbeitung einzelner Datei-Ergebnisse eines Konvertierungslaufs."""
from __future__ import annotations

from pathlib import Path

from ..core.conversion_artifacts import ConversionArtifactBundle
from ..core.result_status import (
    POSTPROCESS_PENDING_ICON,
    POSTPROCESS_PENDING_STATUS,
    accepts_result,
)


def _worker_mapping(thread, session_attr: str, legacy_attr: str) -> dict:
    """Read refactored ConverterSessionState first, then the legacy worker view."""
    if thread is None:
        return {}
    session = getattr(thread, "_session_state", None)
    value = getattr(session, session_attr, None) if session is not None else None
    if isinstance(value, dict):
        return value
    legacy = getattr(thread, legacy_attr, {})
    return legacy if isinstance(legacy, dict) else {}


class ConversionResultFileEventsMixin:
    """Pflegt Queue-/Session-State für file_result-Signale."""

    def on_file_result(self, input_path: str, output_path: str, status: str) -> None:
        state = self._state
        previous = getattr(state, "artifacts_by_input", {}).get(input_path)
        if previous is not None and not accepts_result(previous.status, status):
            return
        display_status = POSTPROCESS_PENDING_ICON if status == POSTPROCESS_PENDING_STATUS else status
        self._set_file_list_item_text(input_path, f"{display_status}  {Path(input_path).name}")
        if status in {"❌", "⚠️", "⏭️"}:
            # Also revoke a previously accepted success (defensive legacy path).
            for path in (input_path, output_path, getattr(previous, "output_path", "")):
                state.fertig.discard(path)
                state.sidecar_outputs_by_video.pop(path, None)
        if status == POSTPROCESS_PENDING_STATUS:
            # Defensive ordering guard: a terminal result always wins. This
            # also protects the GUI from third-party/legacy workers that emit
            # a delayed pending marker after completion.
            if input_path not in state.completed_inputs:
                state.pending_postprocess_inputs.add(input_path)
            self._refresh_queue()
            return
        if status not in {"✅", "❌", "⚠️", "⏭️"}:
            self._refresh_queue()
            return

        state.pending_postprocess_inputs.discard(input_path)
        state.completed_inputs.add(input_path)
        thread = self._state.thread
        bundle = ConversionArtifactBundle.from_worker(
            thread, input_path, output_path=output_path, status=status
        )
        state.artifacts_by_input[input_path] = bundle
        self._record_terminal_result(input_path, output_path, status)
        self._record_journal_result(input_path, output_path, status)
        notify_terminal = getattr(self, "notify_terminal_result", None)
        if callable(notify_terminal):
            notify_terminal(input_path, output_path, status)
        notifications = getattr(self, "_notifications", None)
        if notifications is not None:
            row = state.run_results.get(input_path, {})
            notifications.on_file_result(input_path, status, str(row.get("message") or ""))

        if input_path in state.pending_remove_paths:
            state.pending_remove_paths.discard(input_path)
            self._ui.file_list.remove_path(input_path)
            state.file_overrides.pop(input_path, None)
            state.planned_targets.pop(input_path, None)
            state.planned_targets.pop(output_path, None)
            state.artifacts_by_input.pop(input_path, None)
            state.sidecar_outputs_by_video.pop(output_path, None)
            self._log(
                f"⏭️ '{Path(input_path).name}' wurde nach Abschluss aus der Queue entfernt.",
                "info",
            )
            self._refresh_queue()
            return

        if status == "✅":
            blocked_inputs = set()
            replace_service = getattr(
                getattr(self._state.thread, "_replace_service", None),
                "blocked_move_inputs",
                None,
            )
            if replace_service is not None:
                blocked_inputs = set(replace_service)
            if input_path not in blocked_inputs:
                state.fertig.add(output_path)
                sidecars = list(bundle.sidecars)
                state.sidecar_outputs_by_video[output_path] = sidecars
                self._update_result_sidecars(input_path, sidecars)

                postprocess = [dict(item) for item in bundle.postprocess]
                self._update_result_postprocess(input_path, postprocess)

            planned_target = state.planned_targets.get(input_path)
            if planned_target and output_path != input_path:
                override = state.file_overrides.pop(input_path, None)
                state.planned_targets[output_path] = planned_target
                state.planned_targets.pop(input_path, None)
                if override is not None:
                    state.file_overrides[output_path] = override

        self._refresh_queue()
        if state.finish_waiting_for_postprocess and not state.pending_postprocess_inputs:
            state.finish_waiting_for_postprocess = False
            self.on_finished()

    def _record_terminal_result(self, input_path: str, output_path: str, status: str) -> None:
        if status not in {"✅", "❌", "⚠️", "⏭️"}:
            return
        status_key = {
            "✅": "ok",
            "❌": "error",
            "⚠️": "error",
            "⏭️": "skipped",
        }.get(status, "error")
        details = {}
        if status_key in {"error", "skipped"}:
            bundle = self._state.artifacts_by_input.get(input_path)
            if bundle is not None:
                details = dict(bundle.failure or {})
            else:
                thread = self._state.thread
                detail_map = _worker_mapping(thread, "failure_details", "_failure_details")
                details = dict(detail_map.get(input_path, {}) or {})
        self._state.run_results[input_path] = {
            "input_path": input_path,
            "output_path": output_path if status_key == "ok" else "",
            "status": status_key,
            "sidecars": [],
            "postprocess": [],
            "message": str(details.get("message", "") or ""),
            "error_report": str(details.get("error_report", "") or ""),
            "pipeline": str(details.get("pipeline", "") or ""),
            "container": str(details.get("container", "") or ""),
            "strategy": str(details.get("strategy", "") or ""),
        }

    def _record_journal_result(self, input_path: str, output_path: str, status: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        row = self._state.run_results.get(input_path, {})
        message = str(row.get("message", "") or "")
        try:
            journal.finish_file(
                input_path,
                output_path=output_path if row.get("status") == "ok" else "",
                status=status,
                message=message,
            )
            current_paths = getattr(self._state, "job_journal_current_paths", set())
            current_paths.discard(input_path)
            self._state.job_journal_current_path = next(iter(current_paths), None)
        except Exception as exc:
            self._log(f"⚠️ Job-Journal konnte Ergebnis nicht speichern: {exc}", "warn")

    def _update_result_sidecars(self, input_path: str, sidecars: list[str]) -> None:
        row = self._state.run_results.get(input_path)
        if row is not None:
            row["sidecars"] = list(sidecars or [])

    def _update_result_postprocess(self, input_path: str, postprocess: list[dict]) -> None:
        row = self._state.run_results.get(input_path)
        if row is not None:
            row["postprocess"] = [dict(item) for item in (postprocess or [])]

    def _set_file_list_item_text(self, path: str, text: str) -> None:
        from .ui_helpers import set_file_list_item_text

        set_file_list_item_text(self._ui.file_list, path, text)
