# -*- coding: utf-8 -*-
"""ComfyUI bridge nodes for the external HDRTVDM repository.

No third-party HDRTVDM source or weights are bundled. The loader imports the
user-provided official repository at runtime. The full-video node streams
filtered SDR frames from FFmpeg through HDRTVDM and directly back into FFmpeg,
so complete movies do not require a huge temporary TIFF/PNG sequence.
"""
from __future__ import annotations

import importlib.util
import json
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

import imageio.v2 as imageio
import numpy as np
import torch

try:
    from comfy.model_management import throw_exception_if_processing_interrupted as _check_interrupt
except ImportError:  # pragma: no cover - only absent outside ComfyUI
    def _check_interrupt() -> None:
        return None


_PROCESS_INACTIVITY_TIMEOUT_S = 600.0

_HDR_RGB_TO_YUV = (
    "zscale=matrixin=gbr:matrix=bt2020nc:"
    "primariesin=bt2020:primaries=bt2020:"
    "transferin=smpte2084:transfer=smpte2084:"
    "rangein=full:range=limited,format=yuv420p10le"
)


def _network_class(repo_root: str):
    network_file = Path(repo_root).expanduser() / "method" / "network.py"
    if not network_file.is_file():
        raise FileNotFoundError(f"HDRTVDM network.py not found: {network_file}")
    spec = importlib.util.spec_from_file_location("dragon_hdrtvdm_network", network_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import HDRTVDM network: {network_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    network = getattr(module, "TriSegNet", None)
    if network is None:
        raise ImportError("HDRTVDM TriSegNet class not found")
    return network


def _load_state(path: Path) -> dict[str, Any]:
    try:
        state = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(path, map_location="cpu")
    if isinstance(state, dict) and isinstance(state.get("state_dict"), dict):
        state = state["state_dict"]
    if not isinstance(state, dict):
        raise ValueError("HDRTVDM checkpoint does not contain a state dict")
    return state


def _convert_batch(model: dict[str, Any], images: torch.Tensor) -> torch.Tensor:
    net = model["net"]
    device = model["device"]
    dtype = model["dtype"]
    batch = images.movedim(-1, 1).to(device=device, dtype=dtype)
    height, width = batch.shape[-2:]
    pad_h = (-height) % 4
    pad_w = (-width) % 4
    if pad_h or pad_w:
        batch = torch.nn.functional.pad(batch, (0, pad_w, 0, pad_h), mode="reflect")
    with torch.inference_mode():
        output = net(batch)
    output = output[..., :height, :width].float().clamp(0.0, 1.0)
    return output.movedim(1, -1).cpu()


class DragonHDRTVDMModelLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "repo_root": ("STRING", {"default": ""}),
            "checkpoint": ("STRING", {"default": ""}),
            "device": (["cuda", "cpu"], {"default": "cuda"}),
            "precision": (["fp16", "fp32"], {"default": "fp16"}),
        }}

    RETURN_TYPES = ("DRAGON_HDRTVDM_MODEL",)
    FUNCTION = "load"
    CATEGORY = "DragonTools/HDR"

    def load(self, repo_root: str, checkpoint: str, device: str, precision: str):
        repo = Path(repo_root).expanduser()
        model_path = Path(checkpoint).expanduser()
        if not model_path.is_absolute():
            model_path = repo / model_path
        if not model_path.is_file():
            raise FileNotFoundError(f"HDRTVDM checkpoint not found: {model_path}")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested for HDRTVDM but no CUDA device is available")

        target = torch.device(device)
        dtype = torch.float16 if target.type == "cuda" and precision == "fp16" else torch.float32
        net = _network_class(str(repo))().to(dtype=dtype)
        net.load_state_dict(_load_state(model_path), strict=True)
        net.eval().to(target)
        return ({"net": net, "device": target, "dtype": dtype, "checkpoint": str(model_path)},)


class DragonHDRTVDMVideoConvert:
    """Streaming complete-file SDR->HDR conversion for DragonTools."""

    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("DRAGON_HDRTVDM_MODEL",),
            "input_video": ("STRING", {"default": ""}),
            "output_video": ("STRING", {"default": ""}),
            "ffmpeg_path": ("STRING", {"default": "ffmpeg"}),
            "decode_args_json": ("STRING", {"default": "[]", "multiline": True}),
            "encode_args_json": ("STRING", {"default": "[]", "multiline": True}),
            "hdr_args_json": ("STRING", {"default": "[]", "multiline": True}),
            "fps_num": ("INT", {"default": 24000, "min": 1}),
            "fps_den": ("INT", {"default": 1001, "min": 1}),
            "batch_size": ("INT", {"default": 1, "min": 1, "max": 16}),
            "expected_frames": ("INT", {"default": 0, "min": 0}),
            "manifest_path": ("STRING", {"default": ""}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video", "manifest")
    FUNCTION = "convert_video"
    CATEGORY = "DragonTools/HDR"

    def convert_video(
        self,
        model: dict[str, Any],
        input_video: str,
        output_video: str,
        ffmpeg_path: str,
        decode_args_json: str,
        encode_args_json: str,
        hdr_args_json: str,
        fps_num: int,
        fps_den: int,
        batch_size: int,
        expected_frames: int,
        manifest_path: str,
    ):
        _validate_job_paths(input_video, output_video, manifest_path)
        _check_job_stop(Path(manifest_path).expanduser())
        started = time.monotonic()
        output = Path(output_video).expanduser()
        manifest = Path(manifest_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        decode_args = _json_arg_list(decode_args_json, "decode_args_json")
        encode_args = _json_arg_list(encode_args_json, "encode_args_json")
        hdr_args = _json_arg_list(hdr_args_json, "hdr_args_json")
        fps_num, fps_den = int(fps_num), int(fps_den)
        if fps_num <= 0 or fps_den <= 0:
            raise ValueError("Invalid CFR frame rate")

        decoder = None
        encoder = None
        frame_reader = None
        encoder_writer = None
        decoder_err = tempfile.TemporaryFile(mode="w+b")
        encoder_err = tempfile.TemporaryFile(mode="w+b")
        frames = 0
        try:
            if model["device"].type == "cuda":
                torch.cuda.reset_peak_memory_stats(model["device"])
            _write_manifest(manifest, success=False, state="starting", frames=0, expected_frames=expected_frames)
            decoder = subprocess.Popen(
                _decoder_command(ffmpeg_path, input_video, decode_args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=decoder_err,
                **_no_window_kwargs(),
            )
            if decoder.stdout is None:
                raise RuntimeError("FFmpeg decoder stdout is unavailable")
            frame_reader = _PPMFrameReader(decoder, timeout_s=_PROCESS_INACTIVITY_TIMEOUT_S, check_stop=lambda: _check_job_stop(manifest))
            batch: list[np.ndarray] = []
            last_manifest_write = time.monotonic()
            while True:
                _check_job_stop(manifest)
                frame = frame_reader.read()
                if frame is None:
                    break
                batch.append(frame)
                if len(batch) < max(1, int(batch_size)):
                    continue
                encoder, encoder_writer, count = _process_batch(
                    model, batch, encoder, encoder_writer, encoder_err,
                    ffmpeg_path=ffmpeg_path, output=output,
                    encode_args=encode_args, hdr_args=hdr_args,
                    fps_num=fps_num, fps_den=fps_den,
                    check_stop=lambda: _check_job_stop(manifest),
                )
                frames += count
                batch.clear()
                now = time.monotonic()
                if now - last_manifest_write >= 0.5:
                    _write_manifest(manifest, success=False, state="running", frames=frames, expected_frames=expected_frames)
                    last_manifest_write = now
            if batch:
                encoder, encoder_writer, count = _process_batch(
                    model, batch, encoder, encoder_writer, encoder_err,
                    ffmpeg_path=ffmpeg_path, output=output,
                    encode_args=encode_args, hdr_args=hdr_args,
                    fps_num=fps_num, fps_den=fps_den,
                    check_stop=lambda: _check_job_stop(manifest),
                )
                frames += count
                batch.clear()
            decoder_rc = _wait_process(decoder, "FFmpeg decoder", timeout_s=30.0, check_stop=lambda: _check_job_stop(manifest))
            if decoder_rc != 0:
                raise RuntimeError("FFmpeg decoder failed: " + _stderr_text(decoder_err))
            if int(expected_frames) > 0 and frames != int(expected_frames):
                raise RuntimeError(
                    f"Frame count mismatch: source metadata={int(expected_frames)}, HDRTVDM output={frames}"
                )
            if encoder is None or encoder_writer is None:
                raise RuntimeError("No video frames were decoded")
            _check_job_stop(manifest)
            encoder_writer.close()
            encoder_writer = None
            encoder_rc = _wait_process(encoder, "FFmpeg HDR encoder", timeout_s=_PROCESS_INACTIVITY_TIMEOUT_S, check_stop=lambda: _check_job_stop(manifest))
            if encoder_rc != 0:
                raise RuntimeError("FFmpeg HDR encoder failed: " + _stderr_text(encoder_err))
            if not output.is_file() or output.stat().st_size <= 0:
                raise RuntimeError("FFmpeg HDR encoder produced no output file")

            elapsed = time.monotonic() - started
            peak = int(torch.cuda.max_memory_allocated(model["device"])) if model["device"].type == "cuda" else 0
            _write_manifest(
                manifest, success=True, state="complete", frames=frames,
                expected_frames=expected_frames, elapsed_s=elapsed,
                peak_vram_bytes=peak, fps=f"{fps_num}/{fps_den}", input_path=str(Path(input_video).resolve()), output_path=str(output.resolve()),
            )
            return str(output), str(manifest)
        except BaseException as exc:
            if encoder_writer is not None:
                encoder_writer.abort()
            _terminate(decoder)
            _terminate(encoder)
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            _write_manifest(
                manifest, success=False, state="failed", frames=frames,
                expected_frames=expected_frames, elapsed_s=time.monotonic() - started,
                error=type(exc).__name__, message=str(exc),
            )
            raise
        finally:
            if frame_reader is not None:
                frame_reader.close()
            if encoder_writer is not None:
                encoder_writer.abort()
            _close_process_streams(decoder)
            _close_process_streams(encoder)
            decoder_err.close()
            encoder_err.close()


class DragonFrameSequenceLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "input_dir": ("STRING", {"default": ""}),
            "start_index": ("INT", {"default": 0, "min": 0}),
            "batch_size": ("INT", {"default": 1, "min": 1, "max": 32}),
            "extension": (["png", "tif", "tiff"], {"default": "png"}),
        }}

    RETURN_TYPES = ("IMAGE", "INT", "BOOLEAN")
    RETURN_NAMES = ("images", "next_index", "done")
    FUNCTION = "load"
    CATEGORY = "DragonTools/HDR"

    def load(self, input_dir: str, start_index: int, batch_size: int, extension: str):
        root = Path(input_dir).expanduser()
        files = sorted(root.glob(f"*.{extension}"))
        selected = files[start_index:start_index + batch_size]
        if not selected:
            raise ValueError(f"No input frames at index {start_index} in {root}")
        frames = [_read_frame(path) for path in selected]
        images = torch.from_numpy(np.stack(frames, axis=0)).float()
        next_index = start_index + len(selected)
        return images, next_index, next_index >= len(files)


class DragonHDRTVDMConvert:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("DRAGON_HDRTVDM_MODEL",), "images": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "convert"
    CATEGORY = "DragonTools/HDR"

    def convert(self, model: dict[str, Any], images: torch.Tensor):
        return (_convert_batch(model, images),)


class DragonHDR16TiffWriter:
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "output_dir": ("STRING", {"default": ""}),
            "prefix": ("STRING", {"default": "frame"}),
            "start_index": ("INT", {"default": 0, "min": 0}),
        }}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    CATEGORY = "DragonTools/HDR"

    def save(self, images: torch.Tensor, output_dir: str, prefix: str, start_index: int):
        root = Path(output_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        last = ""
        for offset, frame in enumerate(images.detach().cpu().numpy()):
            path = root / f"{prefix}_{start_index + offset:08d}.tif"
            rgb16 = np.round(np.clip(frame, 0.0, 1.0) * 65535.0).astype(np.uint16)
            imageio.imwrite(path, rgb16)
            last = str(path)
        return (last,)


def _check_job_stop(manifest: Path) -> None:
    _check_interrupt()
    if Path(str(manifest) + '.cancel').is_file():
        raise RuntimeError('DragonTools job cancelled')


def _validate_job_paths(input_path, output_path, manifest_path) -> None:
    paths = [Path(str(p)).expanduser() for p in (input_path, output_path, manifest_path, str(manifest_path) + '.cancel')]
    for pos, path in enumerate(paths):
        for other in paths[:pos]:
            if path.resolve() == other.resolve() or (path.exists() and other.exists() and path.samefile(other)):
                raise ValueError('Path collision: source, output and manifest must be distinct files')


def _decoder_command(ffmpeg_path: str, input_video: str, decode_args: list[str]) -> list[str]:
    return [
        ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", input_video,
        *decode_args, "-an", "-sn", "-dn", "-fps_mode", "passthrough",
        "-c:v", "ppm", "-f", "image2pipe", "pipe:1",
    ]


def _encoder_command(
    ffmpeg_path: str, output: Path, encode_args: list[str], hdr_args: list[str],
    width: int, height: int, fps_num: int, fps_den: int,
) -> list[str]:
    return [
        ffmpeg_path, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb48le", "-video_size", f"{width}x{height}",
        "-framerate", f"{fps_num}/{fps_den}", "-color_range", "pc",
        "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-i", "pipe:0",
        "-vf", _HDR_RGB_TO_YUV, *encode_args, "-an", "-sn", "-dn", *hdr_args,
        "-fps_mode", "cfr", str(output),
    ]


def _process_batch(
    model: dict[str, Any], batch: list[np.ndarray], encoder, encoder_writer, encoder_err,
    *, ffmpeg_path: str, output: Path, encode_args: list[str], hdr_args: list[str],
    fps_num: int, fps_den: int, check_stop=None,
):
    (check_stop or _check_interrupt)()
    source = torch.from_numpy(np.stack(batch, axis=0)).float().div_(255.0)
    converted = _convert_batch(model, source)
    pixels = converted.numpy()
    if pixels.ndim != 4 or pixels.shape[0] != len(batch) or pixels.shape[-1] != 3 or not np.isfinite(pixels).all():
        raise ValueError('HDRTVDM model must return one finite RGB image per source frame')
    height, width = int(converted.shape[1]), int(converted.shape[2])
    if encoder is None:
        encoder = subprocess.Popen(
            _encoder_command(ffmpeg_path, output, encode_args, hdr_args, width, height, fps_num, fps_den),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=encoder_err,
            **_no_window_kwargs(),
        )
    if encoder.stdin is None:
        raise RuntimeError("FFmpeg HDR encoder stdin is unavailable")
    if encoder_writer is None:
        encoder_writer = _ProcessStdinWriter(encoder, timeout_s=_PROCESS_INACTIVITY_TIMEOUT_S, check_stop=check_stop)
    for frame in pixels:
        rgb16 = np.round(np.clip(frame, 0.0, 1.0) * 65535.0).astype("<u2", copy=False)
        encoder_writer.write(rgb16.tobytes(order="C"))
    if encoder.poll() not in (None, 0):
        raise RuntimeError("FFmpeg HDR encoder terminated early: " + _stderr_text(encoder_err))
    return encoder, encoder_writer, len(batch)


class _PPMFrameReader:
    def __init__(self, process, *, timeout_s: float, check_stop=None) -> None:
        self.check_stop = check_stop or _check_interrupt
        self.process = process
        self.timeout_s = max(1.0, float(timeout_s))
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._last_activity = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="DragonHDRTVDM-PPMReader", daemon=True)
        self._thread.start()

    def _put(self, item: tuple[str, object]) -> None:
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.25)
                return
            except queue.Full:
                continue

    def _run(self) -> None:
        stream = self.process.stdout
        try:
            if stream is None:
                raise RuntimeError("FFmpeg decoder stdout is unavailable")
            while not self._stop.is_set():
                frame = _read_ppm_frame(stream)
                if frame is None:
                    self._put(("eof", None))
                    return
                self._put(("frame", frame))
        except BaseException as exc:
            self._put(("error", exc))
        finally:
            _close_stream(stream)

    def read(self) -> np.ndarray | None:
        while True:
            self.check_stop()
            try:
                kind, value = self._queue.get(timeout=0.25)
            except queue.Empty:
                if time.monotonic() - self._last_activity >= self.timeout_s:
                    _terminate(self.process)
                    raise TimeoutError(f"FFmpeg decoder produced no frame for {self.timeout_s:.0f}s")
                continue
            self._last_activity = time.monotonic()
            if kind == "frame":
                return value  # type: ignore[return-value]
            if kind == "eof":
                return None
            if kind == "error":
                raise value  # type: ignore[misc]
            raise RuntimeError(f"Unknown frame-reader event: {kind}")

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            _close_stream(getattr(self.process, "stdout", None))
            self._thread.join(timeout=2.0)


class _ProcessStdinWriter:
    def __init__(self, process, *, timeout_s: float, check_stop=None) -> None:
        self.check_stop = check_stop or _check_interrupt
        if process.stdin is None:
            raise RuntimeError("Process stdin is unavailable")
        self.process = process
        self.stream = process.stdin
        self.timeout_s = max(1.0, float(timeout_s))
        self._queue: queue.Queue[tuple[bytes | None, threading.Event, list[BaseException]]] = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="DragonHDRTVDM-EncoderWriter", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, done, errors = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if data is None:
                    return
                self.stream.write(data)
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

    def write(self, data: bytes) -> None:
        done = threading.Event()
        errors: list[BaseException] = []
        started = time.monotonic()
        while True:
            self.check_stop()
            try:
                self._queue.put((data, done, errors), timeout=0.25)
                break
            except queue.Full:
                if time.monotonic() - started >= self.timeout_s:
                    _terminate(self.process)
                    raise TimeoutError(f"FFmpeg encoder stdin blocked for {self.timeout_s:.0f}s")
        while not done.wait(0.25):
            self.check_stop()
            if self.process.poll() is not None:
                raise RuntimeError("FFmpeg HDR encoder terminated while writing a frame")
            if time.monotonic() - started >= self.timeout_s:
                _terminate(self.process)
                raise TimeoutError(f"FFmpeg encoder stdin blocked for {self.timeout_s:.0f}s")
        if errors:
            raise errors[0]

    def close(self) -> None:
        if self._stop.is_set():
            return
        done = threading.Event()
        errors: list[BaseException] = []
        self._queue.put((None, done, errors))
        done.wait(timeout=2.0)
        self._stop.set()
        _close_stream(self.stream)
        self._thread.join(timeout=2.0)

    def abort(self) -> None:
        self._stop.set()
        # BufferedWriter.close waits for a concurrent blocked write. Stop the
        # owned child first so its pipe releases that writer's lock.
        _terminate(self.process)
        _close_stream(self.stream)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)


def _read_ppm_frame(stream: BinaryIO) -> np.ndarray | None:
    magic = _ppm_token(stream)
    if magic is None:
        return None
    if magic != b"P6":
        raise ValueError(f"Unexpected PPM magic: {magic!r}")
    width_b, height_b, maxval_b = _ppm_token(stream), _ppm_token(stream), _ppm_token(stream)
    if None in (width_b, height_b, maxval_b):
        raise EOFError("Incomplete PPM header")
    width, height, maxval = int(width_b), int(height_b), int(maxval_b)
    if width <= 0 or height <= 0 or maxval != 255:
        raise ValueError(f"Unsupported PPM frame {width}x{height}, maxval={maxval}")
    raw = _read_exact(stream, width * height * 3)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()


def _ppm_token(stream: BinaryIO) -> bytes | None:
    token = bytearray()
    while True:
        char = stream.read(1)
        if not char:
            return bytes(token) if token else None
        if char == b"#" and not token:
            while char not in {b"", b"\n", b"\r"}:
                char = stream.read(1)
            continue
        if char.isspace():
            if token:
                return bytes(token)
            continue
        token.extend(char)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise EOFError(f"Unexpected EOF while reading PPM pixels ({len(chunks)}/{size})")
        chunks.extend(part)
    return bytes(chunks)


def _json_arg_list(raw: str, label: str) -> list[str]:
    value = json.loads(str(raw or "[]"))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must contain a JSON string array")
    return value


def _write_manifest(path: Path, **payload: Any) -> None:
    # Ephemeral progress is advisory; readers retry incomplete writes. Writing
    # the existing file avoids Windows rename/sharing violations from readers.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _stderr_text(file_obj) -> str:
    try:
        file_obj.flush()
        file_obj.seek(0)
        return file_obj.read().decode("utf-8", errors="replace").strip()[-4000:]
    except Exception:
        return ""


def _close_stream(stream) -> None:
    if stream is None:
        return
    try:
        stream.close()
    except (OSError, ValueError):
        pass


def _close_process_streams(process) -> None:
    if process is None:
        return
    for name in ("stdin", "stdout", "stderr"):
        _close_stream(getattr(process, name, None))


def _wait_process(process, label: str, *, timeout_s: float, check_stop=None) -> int:
    deadline = time.monotonic() + max(1.0, float(timeout_s))
    while True:
        (check_stop or _check_interrupt)()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate(process)
            raise TimeoutError(f"{label} did not exit within {timeout_s:.0f}s")
        try:
            return int(process.wait(timeout=min(0.25, remaining)))
        except subprocess.TimeoutExpired:
            continue


def _terminate(process) -> None:
    if process is None:
        return
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=3)
            except Exception:
                pass
    _close_process_streams(process)


def _no_window_kwargs() -> dict[str, Any]:
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flag} if flag else {}


def _read_frame(path: Path) -> np.ndarray:
    frame = np.asarray(imageio.imread(path))
    if frame.ndim == 2:
        frame = np.repeat(frame[..., None], 3, axis=2)
    if frame.shape[-1] > 3:
        frame = frame[..., :3]
    if np.issubdtype(frame.dtype, np.integer):
        maximum = float(np.iinfo(frame.dtype).max)
        return frame.astype(np.float32) / maximum
    return np.clip(frame.astype(np.float32), 0.0, 1.0)


NODE_CLASS_MAPPINGS = {
    "DragonHDRTVDMModelLoader": DragonHDRTVDMModelLoader,
    "DragonHDRTVDMVideoConvert": DragonHDRTVDMVideoConvert,
    "DragonFrameSequenceLoader": DragonFrameSequenceLoader,
    "DragonHDRTVDMConvert": DragonHDRTVDMConvert,
    "DragonHDR16TiffWriter": DragonHDR16TiffWriter,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DragonHDRTVDMModelLoader": "DragonTools HDRTVDM Model Loader",
    "DragonHDRTVDMVideoConvert": "DragonTools HDRTVDM Full Video",
    "DragonFrameSequenceLoader": "DragonTools Frame Sequence Loader",
    "DragonHDRTVDMConvert": "DragonTools HDRTVDM SDR→HDR",
    "DragonHDR16TiffWriter": "DragonTools HDR 16-bit TIFF Writer",
}
