# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction

from ..core.process_runner import tool_available


@dataclass(frozen=True, slots=True)
class PacketStreamSnapshot:
    stream_index: int
    codec_type: str
    ordinal: int
    packet_count: int
    hashes: tuple[str, ...]
    max_pts_s: float | None
    max_dts_s: float | None
    max_duration_s: float | None


@dataclass(frozen=True, slots=True)
class PacketIntegrityResult:
    ok: bool
    available: bool = True
    messages: tuple[str, ...] = ()


class PacketIntegrityVerifier:
    """Bitgenaue Paketprüfung für verlustfreie Timestamp-Reparaturen.

    Die Hashlisten werden pro Stream verglichen. Die globale Paket-Reihenfolge
    darf sich beim Remux ändern; die Nutzdaten innerhalb jedes einzelnen
    Streams müssen dagegen exakt identisch bleiben.
    """

    def __init__(self, *, ffprobe_path: str, run_tool) -> None:
        self._ffprobe_path = str(ffprobe_path or "")
        self._run_tool = run_tool

    def validate(
        self,
        before_path: str,
        after_path: str,
        *,
        reference_duration_s: float | None,
        frame_rate: Fraction | None,
        tolerance_s: float = 0.4,
    ) -> PacketIntegrityResult:
        if not tool_available(self._ffprobe_path):
            return PacketIntegrityResult(True, False, ("ffprobe fehlt für die Paket-/Hashprüfung; 3-Tool-/Dauerprüfung bleibt aktiv.",))
        try:
            before = self._snapshot(before_path)
            after = self._snapshot(after_path)
        except Exception as exc:
            return PacketIntegrityResult(
                True, False,
                (f"Paket-/Hashprüfung war nicht verfügbar: {exc}. 3-Tool-/Dauerprüfung bleibt aktiv.",),
            )

        messages: list[str] = []
        before_keys = {(item.codec_type, item.ordinal) for item in before}
        after_keys = {(item.codec_type, item.ordinal) for item in after}
        if before_keys != after_keys:
            messages.append(
                "Streamstruktur der Paketprüfung ist verändert: "
                f"vorher={sorted(before_keys)}, nachher={sorted(after_keys)}."
            )

        before_map = {(item.codec_type, item.ordinal): item for item in before}
        after_map = {(item.codec_type, item.ordinal): item for item in after}
        for key in sorted(before_keys & after_keys):
            old = before_map[key]
            new = after_map[key]
            label = f"{key[0]} #{key[1] + 1}"
            if old.packet_count != new.packet_count:
                messages.append(
                    f"{label}: Paketanzahl verändert ({old.packet_count} → {new.packet_count})."
                )
                continue
            if old.hashes != new.hashes:
                first_diff = self._first_hash_difference(old.hashes, new.hashes)
                suffix = f" ab Paket {first_diff + 1}" if first_diff is not None else ""
                messages.append(f"{label}: Paket-Nutzdatenhashes unterscheiden sich{suffix}.")

        video = next((item for item in after if item.codec_type == "video" and item.ordinal == 0), None)
        if video is None:
            messages.append("Paketprüfung findet keinen primären Videostream.")
        else:
            if video.max_pts_s is not None:
                if video.max_pts_s >= 1_000_000.0:
                    messages.append(
                        f"Video-PTS weiterhin im Millionen-Sekunden-Bereich ({video.max_pts_s:.3f}s)."
                    )
                if reference_duration_s is not None and video.max_pts_s > float(reference_duration_s) + float(tolerance_s):
                    messages.append(
                        f"Maximaler Video-PTS liegt {video.max_pts_s:.3f}s hinter der erlaubten Referenz "
                        f"{float(reference_duration_s):.3f}s + {float(tolerance_s):.3f}s."
                    )
            if video.max_duration_s is not None and frame_rate is not None and frame_rate > 0:
                normal_frame_s = float(Fraction(1, 1) / frame_rate)
                allowed_packet_s = max(normal_frame_s * 4.0, 0.100)
                if video.max_duration_s > allowed_packet_s:
                    messages.append(
                        f"Ungewöhnlich große Videopaketdauer nach Reparatur: {video.max_duration_s:.6f}s "
                        f"(normal ca. {normal_frame_s:.6f}s, Grenze {allowed_packet_s:.6f}s)."
                    )

        return PacketIntegrityResult(not messages, True, tuple(messages))

    def _snapshot(self, path: str) -> tuple[PacketStreamSnapshot, ...]:
        command = [
            self._ffprobe_path,
            "-v", "error",
            "-show_streams",
            "-show_packets",
            "-show_data_hash", "sha256",
            "-show_entries",
            "stream=index,codec_type:packet=stream_index,pts_time,dts_time,duration_time,data_hash",
            "-of", "json",
            str(path),
        ]
        run = self._run_tool(command, label="ffprobe Paket-/SHA256-Prüfung")
        if getattr(run, "returncode", 1) != 0:
            detail = str(getattr(run, "stderr", "") or getattr(run, "stdout", "") or "ffprobe fehlgeschlagen")
            raise RuntimeError(detail.strip())
        payload = json.loads(str(getattr(run, "stdout", "") or "{}"))
        streams = [
            stream for stream in (payload.get("streams") or [])
            if str(stream.get("codec_type") or "") in {"video", "audio", "subtitle"}
        ]
        streams.sort(key=lambda item: int(item.get("index", 0)))
        ordinals: dict[str, int] = {"video": 0, "audio": 0, "subtitle": 0}
        meta: dict[int, tuple[str, int]] = {}
        for stream in streams:
            index = int(stream.get("index", 0))
            kind = str(stream.get("codec_type") or "")
            ordinal = ordinals[kind]
            ordinals[kind] += 1
            meta[index] = (kind, ordinal)

        packet_rows: dict[int, list[dict]] = {index: [] for index in meta}
        for packet in payload.get("packets") or []:
            try:
                index = int(packet.get("stream_index"))
            except (TypeError, ValueError):
                continue
            if index in packet_rows:
                packet_rows[index].append(packet)

        snapshots: list[PacketStreamSnapshot] = []
        for index, (kind, ordinal) in sorted(meta.items(), key=lambda item: item[0]):
            packets = packet_rows.get(index, [])
            hashes = tuple(str(packet.get("data_hash") or "") for packet in packets)
            if packets and any(not value for value in hashes):
                raise ValueError(f"ffprobe lieferte für {kind} #{ordinal + 1} nicht für jedes Paket einen SHA-256-Hash")
            snapshots.append(
                PacketStreamSnapshot(
                    stream_index=index,
                    codec_type=kind,
                    ordinal=ordinal,
                    packet_count=len(packets),
                    hashes=hashes,
                    max_pts_s=self._max_time(packets, "pts_time"),
                    max_dts_s=self._max_time(packets, "dts_time"),
                    max_duration_s=self._max_time(packets, "duration_time"),
                )
            )
        return tuple(snapshots)

    @staticmethod
    def _max_time(packets: list[dict], key: str) -> float | None:
        values: list[float] = []
        for packet in packets:
            try:
                value = float(packet.get(key))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        return max(values) if values else None

    @staticmethod
    def _first_hash_difference(before: tuple[str, ...], after: tuple[str, ...]) -> int | None:
        for index, (left, right) in enumerate(zip(before, after)):
            if left != right:
                return index
        if len(before) != len(after):
            return min(len(before), len(after))
        return None
