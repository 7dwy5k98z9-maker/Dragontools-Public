"""Conservative repair of 1..5 redundant black pictures at HEVC boundaries.

Do not cut VCL NALs by picture ordinal: HEVC coding order differs from display
order when B pictures are present. Re-encode the affected GOP(s), retain the
untouched bytes, and commit only after strict full decode/timeline validation.
All work is exceptional-path only; normal encodes pay no additional decode.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .dv_encode_command import build_dv_encode_command, primary_ffmpeg_video_index
from .dv_partial_frame_repair import inspect_hevc_irap, _force_closed_gop_headers
from .dv_pipeline_timeouts import timeout_encode
from .frame_count_evidence import temporal_mapping_for_filters


_WIDTH, _HEIGHT = 16, 9
_FRAME_BYTES = _WIDTH * _HEIGHT
_MAX_EXTRA = 5
_MAX_REENCODE_FRAMES = 2000
_MAX_FRAME_MAE = 5.0


@dataclass(frozen=True)
class EdgeExtras:
    head: int
    tail: int


@dataclass(frozen=True)
class EdgeWindow:
    head_end: int
    head_byte_end: int
    tail_start: int
    tail_byte_start: int


def choose_edge_window(iraps, *, edges: EdgeExtras, expected: int, actual: int, size: int) -> EdgeWindow | None:
    # Coding-order ordinals are safe for a retained prefix before an IRAP:
    # re-encode all following pictures, including leading RASL pictures.
    # A retained suffix requires IDR/BLA, which has no leading RASL.
    head_end, head_byte_end = 0, 0
    if edges.head:
        boundaries = [p for p in iraps if p.is_strong_boundary and p.frame_index > edges.head + 16]
        if not boundaries:
            return None
        first = boundaries[0]
        head_end, head_byte_end = first.frame_index, first.byte_offset
        if head_end > _MAX_REENCODE_FRAMES:
            return None
    tail_start, tail_byte_start = actual, size
    if edges.tail:
        boundaries = [p for p in iraps if p.frame_index < actual - edges.tail - 16]
        if not boundaries:
            return None
        last = boundaries[-1]
        tail_start, tail_byte_start = last.frame_index, last.byte_offset
        if actual - tail_start > _MAX_REENCODE_FRAMES:
            return None
    if head_end >= tail_start:
        # For a short clip the boundary GOPs may overlap. Never turn a film
        # repair into an unexpected full re-encode.
        if expected > _MAX_REENCODE_FRAMES:
            return None
        head_end, head_byte_end = actual, size
        tail_start, tail_byte_start = actual, size
    return EdgeWindow(head_end, head_byte_end, tail_start, tail_byte_start)


def _mae(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / _FRAME_BYTES


def _black(frame: bytes) -> bool:
    # Gray conversion expands limited-range black to zero. These tight bounds
    # allow small codec noise but reject white/flat pictures (dHash == 0 too).
    return len(frame) == _FRAME_BYTES and max(frame) <= 12 and sum(frame) <= 4 * _FRAME_BYTES


def _frames(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if not data or len(data) % _FRAME_BYTES:
        return []
    return [data[i:i + _FRAME_BYTES] for i in range(0, len(data), _FRAME_BYTES)]


def timeline_matches(source: list[bytes], encoded: list[bytes], *, head: int = 0) -> bool:
    """Check every aligned frame, plus distributed motion anchors.

    Low-resolution luma preserves brightness, unlike dHash. Reject a better
    neighbouring-frame alignment in runs, so a small interior insertion cannot
    be mistaken for an edge insertion just because both ends are black. A fully
    static/black clip gives no reliable alignment evidence and is rejected.
    """
    count = len(source)
    if count < 48 or head < 0 or head + count > len(encoded):
        return False
    anchors = [0, 0, 0]
    shifted_run = 0
    for i, reference in enumerate(source):
        picture = encoded[i + head]
        score = _mae(reference, picture)
        if score > _MAX_FRAME_MAE:
            return False
        if _MAX_EXTRA <= i < count - _MAX_EXTRA:
            alternatives = [
                _mae(source[i + offset], picture)
                for offset in range(-_MAX_EXTRA, _MAX_EXTRA + 1) if offset
            ]
            best = min(alternatives)
            shifted_run = shifted_run + 1 if best + 0.5 < score else 0
            if shifted_run >= 3:
                return False
            if score + 0.5 < best:
                anchors[min(2, i * 3 // count)] += 1
    return all(value >= 3 for value in anchors)


def locate_black_edge_extras(source: list[bytes], encoded: list[bytes]) -> EdgeExtras | None:
    extra = len(encoded) - len(source)
    if not source or not 1 <= extra <= _MAX_EXTRA:
        return None
    matches: list[EdgeExtras] = []
    for head in range(extra + 1):
        tail = extra - head
        if head and not (_black(source[0]) and all(_black(f) for f in encoded[:head])):
            continue
        if tail and not (_black(source[-1]) and all(_black(f) for f in encoded[-tail:])):
            continue
        if timeline_matches(source, encoded, head=head):
            matches.append(EdgeExtras(head, tail))
    return matches[0] if len(matches) == 1 else None


def append_output_filter(command: list, chain: str) -> list:
    """Append after the production graph, keeping P5/crop/subtitle timestamps.

    Accept only the single explicitly mapped video output of our encoder plan.
    An unknown/multi-output graph must fail closed rather than auto-select.
    """
    cmd = list(command)
    if "-filter_complex" in cmd:
        graph_idx = cmd.index("-filter_complex") + 1
        maps = [i + 1 for i, value in enumerate(cmd[:-1]) if value == "-map"]
        if len(maps) != 1:
            raise ValueError("repair requires exactly one mapped graph output")
        target = str(cmd[maps[0]])
        graph = str(cmd[graph_idx])
        if not (target.startswith("[") and target.endswith("]")):
            raise ValueError("repair requires an explicitly labelled graph output")
        output = "[_dv_edge_checked]"
        if output in graph:
            raise ValueError("repair output label already in use")
        cmd[graph_idx] = f"{graph};{target}{chain}{output}"
        cmd[maps[0]] = output
    elif "-vf" in cmd:
        idx = cmd.index("-vf") + 1
        cmd[idx] = f"{cmd[idx]},{chain}" if cmd[idx] else chain
    else:
        idx = cmd.index("-an") if "-an" in cmd else len(cmd) - 1
        cmd[idx:idx] = ["-vf", chain]
    return cmd


def _strict_decode_command(command: list) -> list:
    cmd = list(command)
    # Input decoder options must precede -i; -xerror rejects concealed decoder
    # errors even when FFmpeg would otherwise finish with return code zero.
    cmd[cmd.index("-i"):cmd.index("-i")] = ["-xerror", "-err_detect", "explode"]
    return cmd


def _copy_range(source: Path, out, start: int, end: int) -> None:
    if start < 0 or end < start:
        raise ValueError("invalid HEVC byte range")
    with source.open("rb") as fh:
        fh.seek(start)
        remaining = end - start
        while remaining:
            chunk = fh.read(min(4 * 1024 * 1024, remaining))
            if not chunk:
                raise OSError("HEVC input shortened during repair")
            out.write(chunk)
            remaining -= len(chunk)


class DVEdgeFrameRepair:
    def __init__(self, *, tools, encoder_config, progress_runner,
                 log: Callable, verbose_log: Callable) -> None:
        self._tools = tools
        self._config = encoder_config
        self._progress = progress_runner
        self._log = log
        self._vlog = verbose_log

    def _plan(self, state, output: Path) -> list:
        return build_dv_encode_command(
            ffmpeg_path=self._tools.ffmpeg,
            encoder_config=self._config,
            input_path=state.request.input_path,
            output_hevc=output,
            vf_args=list(state.effective_vf_args or state.request.vf_args),
            profile_major=state.request.profile_major,
            source_stream_index=primary_ffmpeg_video_index(getattr(state.request, "media_info", None)),
        ).command

    def _fingerprint(self, runner, state, input_path: Path, output: Path, *, source: bool) -> list[bytes]:
        fp = f"scale={_WIDTH}:{_HEIGHT}:flags=area,format=gray"
        if source:
            # Retain the exact production inputs and complete filter graph,
            # replacing only the encoder/output. Includes burned subtitles.
            plan = self._plan(state, output)
            cmd = plan[:plan.index("-c:v")]
            cmd += ["-an", "-sn", "-dn", "-fps_mode", "passthrough",
                    "-pix_fmt", "gray", "-f", "rawvideo", str(output)]
            cmd = append_output_filter(cmd, fp)
        else:
            cmd = [self._tools.ffmpeg, "-y", "-nostdin", "-v", "error",
                   "-i", str(input_path), "-map", "0:v:0", "-vf", fp,
                   "-an", "-sn", "-dn", "-fps_mode", "passthrough",
                   "-pix_fmt", "gray", "-f", "rawvideo", str(output)]
        output.unlink(missing_ok=True)
        rc = runner.run(_strict_decode_command(cmd), allow_error=True,
                        timeout=timeout_encode(), label="DV Randframe-Prüfung: vollständiger Bildvergleich")
        return _frames(output) if rc == 0 and output.exists() else []

    def _encode_segment(self, state, output: Path, start: int, end: int) -> bool:
        cmd = append_output_filter(self._plan(state, output),
                                   f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS")
        cmd = _force_closed_gop_headers(cmd)
        # Do not let the overlay EOF bug reproduce an extra output picture.
        # The original count is independently proved by fingerprints first.
        cmd[-1:-1] = ["-frames:v", str(end - start)]
        cmd = _strict_decode_command(cmd)
        output.unlink(missing_ok=True)
        rc = self._progress.run_p(
            cmd, state.request.input_path, self._progress.probe_ms(state.request.input_path),
            timeout_s=timeout_encode(), label="[DV][EDGE-RECOVERY] Rand-GOP neu encodieren",
        )
        if rc != 0 or not output.exists() or output.stat().st_size <= 0:
            return False
        return self._progress.take_output_frame_count(state.request.input_path, process_rc=rc) == end - start

    def attempt(self, *, state, runner, expected_rpu_frames: int, actual_encode_frames: int) -> bool:
        extra = int(actual_encode_frames) - int(expected_rpu_frames)
        vf_args = list(state.effective_vf_args or state.request.vf_args)
        if not 1 <= extra <= _MAX_EXTRA or state.request.profile_major not in {5, 7, 8}:
            return False
        if temporal_mapping_for_filters(vf_args) != "preserved":
            return False
        if str(self._config.options.get("encoder", "cpu") or "cpu").lower() != "cpu":
            self._vlog("[DV][EDGE-RECOVERY] Rand-GOP-Splicing ist nur für CPU/libx265 freigegeben.")
            return False
        if str(self._config.codec).lower() not in {"h265", "hevc", "x265"}:
            return False
        try:
            return self._attempt(state, runner, int(expected_rpu_frames), int(actual_encode_frames))
        except (OSError, ValueError, IndexError) as exc:
            self._vlog(f"[DV][EDGE-RECOVERY] Sichere Randreparatur nicht möglich: {exc}")
            return False

    def _attempt(self, state, runner, expected: int, actual: int) -> bool:
        files = state.files
        root, original = files.root, files.enc_hevc
        backup = root / "encoded_frame_mismatch.hevc"
        if backup.exists():
            self._vlog("[DV][EDGE-RECOVERY] Vorhandener Erstencode wird nicht überschrieben.")
            return False
        self._log(f"⚠️ [DV][EDGE-RECOVERY] Prüfe {actual - expected} mögliche schwarze Zusatzbilder am Anfang/Ende.", "warn")
        source = self._fingerprint(runner, state, Path(state.request.input_path), root / "edge_source.gray", source=True)
        if len(source) != expected:
            self._vlog(f"[DV][EDGE-RECOVERY] Quelle hat {len(source)} statt {expected} Bilder; keine Randkorrektur.")
            return False
        encoded = self._fingerprint(runner, state, original, root / "edge_encoded.gray", source=False)
        if len(encoded) != actual:
            return False
        edges = locate_black_edge_extras(source, encoded)
        if edges is None:
            self._vlog("[DV][EDGE-RECOVERY] Keine eindeutige schwarze Randverlängerung; normaler Fehlerpfad bleibt aktiv.")
            return False
        iraps, parameter_sets, parsed_count = inspect_hevc_irap(original)
        if parsed_count != actual or not parameter_sets:
            return False
        size = original.stat().st_size

        window = choose_edge_window(iraps, edges=edges, expected=expected, actual=actual, size=size)
        if window is None:
            self._vlog("[DV][EDGE-RECOVERY] Keine sichere, begrenzte GOP-Grenze für die Randreparatur.")
            return False
        head_end, head_byte_end = window.head_end, window.head_byte_end
        tail_start, tail_byte_start = window.tail_start, window.tail_byte_start

        candidate = root / "encoded_edge_repair.hevc"
        first_segment = root / "edge_head_segment.hevc"
        last_segment = root / "edge_tail_segment.hevc"
        if head_end:
            source_end = min(expected, head_end - edges.head)
            if head_end == actual:
                source_end = expected
            if not self._encode_segment(state, first_segment, 0, source_end):
                return False
        if tail_start < actual:
            if not self._encode_segment(state, last_segment, tail_start - edges.head, expected):
                return False

        candidate.unlink(missing_ok=True)
        with candidate.open("wb") as out:
            if head_end:
                _copy_range(first_segment, out, 0, first_segment.stat().st_size)
                if head_byte_end < tail_byte_start:
                    out.write(parameter_sets)
            _copy_range(original, out, head_byte_end, tail_byte_start)
            if tail_start < actual:
                _copy_range(last_segment, out, 0, last_segment.stat().st_size)

        pictures = self._fingerprint(runner, state, candidate, root / "edge_candidate.gray", source=False)
        if len(pictures) != expected or not timeline_matches(source, pictures):
            self._vlog("[DV][EDGE-RECOVERY] Kandidat besteht vollständige Bildzahl-/Timeline-Prüfung nicht; Erstencode unverändert.")
            return False
        if inspect_hevc_irap(candidate)[2] != expected:
            return False
        original.replace(backup)
        try:
            candidate.replace(original)
        except OSError:
            backup.replace(original)
            raise
        state.frame_recovery_applied = True
        state.frame_recovery_original_count = actual
        state.frame_recovery_final_count = expected
        state.frame_recovery_message = (
            f"Randreparatur: {edges.head} schwarze Zusatzbilder am Anfang und {edges.tail} am Ende; "
            "Rand-GOPs neu encodiert, vollständige Bildfolge und Bildzahl geprüft."
        )
        self._log(f"✅ [DV][EDGE-RECOVERY] {state.frame_recovery_message} Erstencode bleibt als {backup.name} erhalten.", "info")
        return True
