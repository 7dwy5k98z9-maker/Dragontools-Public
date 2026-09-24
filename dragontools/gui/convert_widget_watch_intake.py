# -*- coding: utf-8 -*-
"""Watch-Folder intake API mixed directly into the converter facade."""
from __future__ import annotations

from PyQt6.QtCore import QTimer

from ..core.encoder_profile_override import profile_to_override
from ..core.models import normalize_override_dict
from ..core.path_syntax import path_compare_key
from ..core.callback_dispatch import invoke_callback, is_callback_like


class ConvertWidgetWatchMixin:
    def enqueue_watch_folder_files(
        self,
        paths: list[str],
        *,
        profile_key: str = "",
        auto_start: bool = True,
        completion_callback=None,
    ) -> list[str]:
        if self._is_queue_blocking_move_active():
            self._log("Watch-Folder wartet: Queue ist während des Verschiebens gesperrt.", "warn")
            return []

        eligible = getattr(self, "_watch_auto_start_eligible", set())
        self._watch_auto_start_eligible = eligible
        owners = getattr(self, "_watch_owned_items", {})
        self._watch_owned_items = owners
        for key, (path, item) in list(owners.items()):
            if self.file_list.item_for_path(path) is not item:
                owners.pop(key, None)
                eligible.discard(key)
                getattr(self, "_watch_completion_callbacks", {}).pop(key, None)
        handled: list[str] = []
        added: list[str] = []
        for path in paths:
            if self.file_list.item_for_path(path) is not None:
                if path_compare_key(path) in owners:
                    handled.append(path)
            elif self.file_list.add_path(path):
                added.append(path)

        profile_override = self._watch_profile_override(profile_key)
        for path in added:
            if profile_override:
                override = dict(self._state.file_overrides.get(path) or {})
                override["encoder_profile"] = dict(profile_override)
                self._state.file_overrides[path] = normalize_override_dict(override)

        rejected = self._watch_live_add(added)
        accepted = [path for path in added if path not in rejected]
        for path in accepted:
            owners[path_compare_key(path)] = (path, self.file_list.item_for_path(path))
        if rejected:
            self._file_queue.remove_rejected_from_gui(list(rejected))
            for path in rejected:
                self._state.file_overrides.pop(path, None)

        if accepted:
            self._file_queue.refresh_labels(accepted)
            self._file_queue.sync_total_files()
            self._file_queue.sync_queue_order()
            self._maybe_preflight_new_files(accepted)
            for path in accepted:
                self.update_queue_label(path)
                self._log(f"👁 Watch-Folder → Queue: {path}", "info")
        self._refresh_queue_window()
        handled.extend(accepted)

        if is_callback_like(completion_callback):
            callbacks = getattr(self, "_watch_completion_callbacks", None)
            if callbacks is None:
                callbacks = {}
                self._watch_completion_callbacks = callbacks
            for path in handled:
                callbacks[path_compare_key(path)] = completion_callback

        if self._active_worker() is None:
            if auto_start:
                # Include already queued Watch-Folder paths as well. This lets a
                # failed/removed Watch-Folder job be picked up again on the next
                # scan without creating a duplicate queue row.
                eligible.update(path_compare_key(path) for path in handled)
                if handled:
                    QTimer.singleShot(0, self._watch_maybe_auto_start)
            else:
                for path in handled:
                    eligible.discard(path_compare_key(path))
        return handled

    def _watch_live_add(self, paths: list[str]) -> set[str]:
        thread = self._state.thread
        if thread is None or not hasattr(thread, "add_file"):
            return set()
        rejected: set[str] = set()
        for path in paths:
            try:
                override = self._state.file_overrides.get(path, {})
                add_with_override = getattr(thread, "add_file_with_override", None)
                ok = add_with_override(path, override) if callable(add_with_override) else thread.add_file(path)
                if ok is not False and override and not callable(add_with_override) and hasattr(thread, "update_override"):
                    thread.update_override(path, override)
                if ok is False:
                    rejected.add(path)
            except Exception as exc:
                self._log(f"Watch-Folder: Live-Hinzufügen fehlgeschlagen: {exc}", "warn")
                rejected.add(path)
        return rejected

    def _watch_maybe_auto_start(self) -> None:
        if self._active_worker() is not None:
            return
        current = self.file_list.get_paths()
        eligible = getattr(self, "_watch_auto_start_eligible", set())
        if not current:
            eligible.clear()
            return
        current_keys = {path_compare_key(path) for path in current}
        owners = getattr(self, "_watch_owned_items", {})
        owned = all(
            path_compare_key(path) in owners
            and owners[path_compare_key(path)][1] is self.file_list.item_for_path(path)
            for path in current
        )
        if not owned or not current_keys.issubset(eligible):
            self._log(
                "Watch-Folder Auto-Start unterdrückt: Queue enthält manuell oder ohne Auto-Start eingereihte Dateien.",
                "info",
            )
            return
        if self.move_cb.isChecked():
            self._log(
                "Watch-Folder Auto-Start angehalten: Verschieben ist aktiv und benötigt den bestehenden Preflight.",
                "warn",
            )
            return
        eligible.clear()
        self._start()

    def _watch_profile_override(self, profile_key: str) -> dict:
        key = str(profile_key or "").strip()
        if not key:
            return {}
        if key not in self.profile_manager.data:
            self._log(f"Watch-Folder-Profil nicht gefunden: {key}; globales Profil wird verwendet.", "warn")
            return {}
        override = profile_to_override(
            key, self.profile_manager.get(key), default_codec=self.default_codec
        )
        if not override:
            self._log(f"Watch-Folder-Profil ist für {self.default_codec} nicht verwendbar: {key}", "warn")
            return {}
        return dict(override)

    def _watch_on_file_result(self, input_path: str, _output_path: str, status: str) -> None:
        """Report a terminal converter result back to the Watch-Folder controller."""
        if status not in {"✅", "❌", "⚠️", "⏭️"}:
            return
        callbacks = getattr(self, "_watch_completion_callbacks", None)
        if not callbacks:
            return
        callback = callbacks.pop(path_compare_key(input_path), None)
        if is_callback_like(callback):
            try:
                invoke_callback(callback, input_path, status == "✅")
            except Exception as exc:
                self._log(f"Watch-Folder: Abschlussstatus konnte nicht zurückgemeldet werden: {exc}", "warn")
