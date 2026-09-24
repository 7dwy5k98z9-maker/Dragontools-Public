from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


torch = pytest.importorskip("torch")
imageio = pytest.importorskip("imageio.v2")


def _load_bridge_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "extras" / "comfyui" / "DragonTools_HDRTVDM" / "nodes.py"
    spec = importlib.util.spec_from_file_location("dragon_hdrtvdm_bridge_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hdrtvdm_bridge_cpu_mock_roundtrip_writes_uint16_tiff(tmp_path: Path):
    bridge = _load_bridge_module()
    repo = tmp_path / "HDRTVDM ä"
    method = repo / "method"
    method.mkdir(parents=True)
    (method / "network.py").write_text(
        "import torch\n"
        "from torch import nn\n"
        "class TriSegNet(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__(); self.conv=nn.Conv2d(3,3,1,bias=False)\n"
        "    def forward(self,x): return self.conv(x)\n",
        encoding="utf-8",
    )
    conv = torch.nn.Conv2d(3, 3, 1, bias=False)
    with torch.no_grad():
        conv.weight.zero_()
        for index in range(3):
            conv.weight[index, index, 0, 0] = 1
    checkpoint = method / "params_3DM.pth"
    torch.save({"conv.weight": conv.weight.detach().clone()}, checkpoint)

    model = bridge.DragonHDRTVDMModelLoader().load(str(repo), str(checkpoint), "cpu", "fp32")[0]
    source = torch.rand(2, 8, 12, 3)
    converted = bridge.DragonHDRTVDMConvert().convert(model, source)[0]
    assert converted.shape == source.shape
    assert torch.allclose(converted, source, atol=1e-6)

    out_dir = tmp_path / "HDR Frames ä"
    last = bridge.DragonHDR16TiffWriter().save(converted, str(out_dir), "frame", 0)[0]
    frame = imageio.imread(last)
    assert frame.dtype.name == "uint16"
    assert frame.shape == (8, 12, 3)


def test_hdrtvdm_streaming_video_node_roundtrip_without_frame_dump(tmp_path: Path):
    import json
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    bridge = _load_bridge_module()
    repo = tmp_path / "HDRTVDM stream"
    method = repo / "method"
    method.mkdir(parents=True)
    (method / "network.py").write_text(
        "import torch\n"
        "from torch import nn\n"
        "class TriSegNet(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__(); self.conv=nn.Conv2d(3,3,1,bias=False)\n"
        "    def forward(self,x): return self.conv(x)\n",
        encoding="utf-8",
    )
    conv = torch.nn.Conv2d(3, 3, 1, bias=False)
    with torch.no_grad():
        conv.weight.zero_()
        for index in range(3):
            conv.weight[index, index, 0, 0] = 1
    checkpoint = method / "params_3DM.pth"
    torch.save({"conv.weight": conv.weight.detach().clone()}, checkpoint)
    model = bridge.DragonHDRTVDMModelLoader().load(str(repo), str(checkpoint), "cpu", "fp32")[0]

    source = tmp_path / "SDR Quelle ä.mkv"
    output = tmp_path / "HDR Ausgabe ä.mkv"
    manifest = tmp_path / "manifest.json"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=4:duration=1",
        "-c:v", "ffv1", str(source),
    ], check=True)

    video, manifest_out = bridge.DragonHDRTVDMVideoConvert().convert_video(
        model, str(source), str(output), ffmpeg,
        json.dumps(["-map", "0:v:0"]),
        json.dumps(["-c:v", "libx265", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p10le"]),
        json.dumps(["-color_range", "tv", "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]),
        4, 1, 1, 4, str(manifest),
    )
    assert Path(video).is_file()
    assert Path(manifest_out) == manifest
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["frames"] == 4
    probe = subprocess.run([
        ffmpeg.replace("ffmpeg", "ffprobe") if ffmpeg.endswith("ffmpeg") else "ffprobe",
        "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt,color_transfer,color_primaries,color_space",
        "-of", "json", str(output),
    ], capture_output=True, text=True)
    if probe.returncode == 0:
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["color_transfer"] == "smpte2084"
        assert stream["color_primaries"] == "bt2020"


def test_hdrtvdm_streaming_node_rejects_expected_frame_mismatch(tmp_path: Path):
    import json
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    bridge = _load_bridge_module()
    repo = tmp_path / "HDRTVDM mismatch"
    method = repo / "method"
    method.mkdir(parents=True)
    (method / "network.py").write_text(
        "import torch\n"
        "from torch import nn\n"
        "class TriSegNet(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__(); self.conv=nn.Conv2d(3,3,1,bias=False)\n"
        "    def forward(self,x): return self.conv(x)\n",
        encoding="utf-8",
    )
    conv = torch.nn.Conv2d(3, 3, 1, bias=False)
    with torch.no_grad():
        conv.weight.zero_()
        for index in range(3):
            conv.weight[index, index, 0, 0] = 1
    checkpoint = method / "params_3DM.pth"
    torch.save({"conv.weight": conv.weight.detach().clone()}, checkpoint)
    model = bridge.DragonHDRTVDMModelLoader().load(str(repo), str(checkpoint), "cpu", "fp32")[0]

    source = tmp_path / "source.mkv"
    output = tmp_path / "out.mkv"
    manifest = tmp_path / "manifest.json"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=4:duration=1",
        "-c:v", "ffv1", str(source),
    ], check=True)

    with pytest.raises(RuntimeError, match="Frame count mismatch"):
        bridge.DragonHDRTVDMVideoConvert().convert_video(
            model, str(source), str(output), ffmpeg,
            json.dumps(["-map", "0:v:0"]),
            json.dumps(["-c:v", "libx265", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p10le"]),
            json.dumps(["-color_range", "tv", "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]),
            4, 1, 1, 5, str(manifest),
        )
    assert not output.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert payload["frames"] == 4
