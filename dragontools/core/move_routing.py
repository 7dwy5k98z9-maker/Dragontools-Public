# -*- coding: utf-8 -*-
"""Zielermittlung fuer Move-Vorgaenge, ohne Qt-Abhaengigkeit."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ..rules.move_rules import (
    find_series_dir_candidates,
    is_planned_move_target_valid,
    move_safe_stem,
    parse_series_match_details,
    planned_target_dir,
    resolve_film_target_for_path,
    resolve_series_root_dir,
    resolve_target_path,
)


def _fmt(path: str) -> str:
    return str(path).replace("/", "\\")


def _similar(a: str, b: str) -> bool:
    an = re.sub(r"\W", "", a.lower())
    bn = re.sub(r"\W", "", b.lower())
    if len(an) < 4 or len(bn) < 4:
        return False
    n = 0
    for ca, cb in zip(an, bn):
        if ca == cb:
            n += 1
        else:
            break
    return n >= min(6, len(an) // 2)


class MoveRouter:
    def __init__(
        self,
        *,
        tv_path: str,
        anime_path: str,
        filme_path: str,
        all_video_files: list[str],
        planned_target_for: Callable[[str], object],
        ask: Callable[[dict], dict],
        log: Callable[[str, str], None],
    ) -> None:
        self.tv_path = tv_path
        self.anime_path = anime_path
        self.filme_path = filme_path
        self.all_video_files = list(all_video_files or [])
        self._planned_target_for = planned_target_for
        self._ask = ask
        self._log = log

    def route(self, path: str) -> str:
        planned_entry = self._planned_target_for(path)
        target_dir = planned_target_dir(planned_entry)
        if target_dir:
            if is_planned_move_target_valid(
                path,
                target_dir,
                tv_path=self.tv_path,
                anime_path=self.anime_path,
                filme_path=self.filme_path,
            ):
                Path(target_dir).mkdir(parents=True, exist_ok=True)
                return target_dir
            self._log(
                f"Geplantes Ziel unplausibel, berechne Ziel neu: {Path(path).name} -> {target_dir}",
                "warn",
            )
        elif planned_entry is not None:
            self._log(f"Geplantes Ziel unlesbar, berechne Ziel neu: {Path(path).name}", "warn")

        name = Path(path).name
        stem = move_safe_stem(path)
        parsed = parse_series_match_details(name)
        if parsed and parsed.get("series"):
            return self.handle_series(path, parsed)
        return self.handle_film(path, stem)

    def handle_series(self, path: str, parsed: dict) -> str:
        series_name = parsed["series"]
        season = parsed["season"]
        bases = []
        if self.tv_path:
            bases.append({"label": f"📺 TV → {_fmt(self.tv_path)}", "path": self.tv_path})
        if self.anime_path:
            bases.append({"label": f"🎌 Anime → {_fmt(self.anime_path)}", "path": self.anime_path})
        if not bases:
            self._log("⚠️ Kein TV/Anime-Pfad konfiguriert.", "warn")
            return ""
        if len(bases) == 1:
            base = bases[0]["path"]
        else:
            resp = self._ask({"type": "choose_series_base_or_folder", "series_name": series_name, "bases": bases})
            if resp.get("abort"):
                return ""
            base = resp.get("base_path", bases[0]["path"])
        return self.find_series_dir(base, series_name, season)

    def find_series_dir(self, base: str, series_name: str, season: int) -> str:
        candidates = [Path(p) for p in find_series_dir_candidates(base, series_name)]
        if len(candidates) == 1:
            series_dir = str(candidates[0])
        elif len(candidates) > 1:
            resp = self._ask({
                "type": "choose_series_folder",
                "series_name": series_name,
                "candidates": [{"label": c.name, "path": str(c)} for c in candidates],
            })
            if resp.get("abort"):
                return ""
            series_dir = str(resp.get("path", str(candidates[0])))
        else:
            series_dir = resolve_series_root_dir(base, series_name)
        target = resolve_target_path(
            kind="series",
            base_path=base,
            series_name=series_name,
            season=season,
            series_dir=series_dir,
        )
        if not target:
            return ""
        Path(target).mkdir(parents=True, exist_ok=True)
        return target

    def handle_film(self, path: str, stem: str) -> str:
        if not self.filme_path:
            self._log("Kein Film-Pfad konfiguriert.", "warn")
            return ""
        similar = [
            candidate
            for candidate in self.all_video_files
            if candidate != path and _similar(move_safe_stem(candidate), stem)
        ]
        resp = self._ask({
            "type": "film_destination",
            "stem": stem,
            "path": path,
            "filme_path": self.filme_path,
            "similar_files": similar,
        })
        if resp.get("abort"):
            return ""
        target = resolve_film_target_for_path(
            path,
            base_path=self.filme_path,
            film_name=resp.get("film_name", stem),
            series_name=resp.get("series_name", stem),
            mode=resp.get("mode", "single"),
            series_dir=resp.get("series_dir"),
            relative_subpath=resp.get("relative_subpath"),
        )
        if not target:
            return ""
        Path(target).mkdir(parents=True, exist_ok=True)
        return target
