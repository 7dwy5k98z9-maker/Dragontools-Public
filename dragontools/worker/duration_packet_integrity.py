# -*- coding: utf-8 -*-
from __future__ import annotations

from tempfile import TemporaryFile
from dataclasses import dataclass
from fractions import Fraction

from ..core.process_runner import tool_available
from .packet_snapshot import PacketStreamSnapshot, read_snapshot
from .verification_control import stopped


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
            return PacketIntegrityResult(False, False, ("ffprobe fehlt für die Paket-/Hashprüfung; automatische Reparaturübernahme gesperrt.",))
        try:
            before = self._snapshot(before_path)
            after = self._snapshot(after_path)
        except Exception as exc:
            return PacketIntegrityResult(
                False, False,
                (f"Paket-/Hashprüfung war nicht verfügbar: {exc}. Automatische Reparaturübernahme gesperrt.",),
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
                messages.append(f"{label}: Paket-Nutzdatenhashes unterscheiden sich.")

        video = next((item for item in after if item.codec_type == "video" and item.ordinal == 0), None)
        if video is None:
            messages.append("Paketprüfung findet keinen primären Videostream.")
        else:
            if video.max_dts_s is not None and video.max_dts_s >= 1_000_000.0:
                messages.append(f'Video-DTS weiterhin im Millionen-Sekunden-Bereich ({video.max_dts_s:.3f}s).')
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
        # The child writes directly to disk; parse one packet at a time.
        with TemporaryFile(mode="w+", encoding="utf-8") as output:
            run = self._run_tool(command, label="ffprobe Paket-/SHA256-Prüfung", stdout_file=output)
            if getattr(run, "returncode", 1) != 0 or stopped(run):
                raise RuntimeError(str(getattr(run, "stderr", "") or "ffprobe fehlgeschlagen")[-4096:])
            # Compatibility with injected test/tool adapters returning text.
            if getattr(run, "stdout", ""):
                output.write(run.stdout)
                run.stdout = ""
            output.seek(0)
            return read_snapshot(output)
