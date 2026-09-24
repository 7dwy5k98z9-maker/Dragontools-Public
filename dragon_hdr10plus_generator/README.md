# Dragon HDR10+ Generator

Standalone CLI component for DragonTools and independent use.

Version `0.2.0` performs a complete PQ/HDR10 analysis pass and writes an
`hdr10plus_tool`-compatible ST-2094-40 **Profile A** JSON file.

## Contract

```text
HDRPlusGenerator --version
HDRPlusGenerator analyze --input <video> --output <hdr10plus.json>
```

stdout contains exactly one JSON object. Progress and diagnostics are written to
stderr so DragonTools can safely consume stdout.

The pipeline is:

```text
final PQ / BT.2020 picture stream
  -> ffprobe validation
  -> ffmpeg full-frame temporal scan (spatially reduced analysis surface)
  -> PQ RGB linearization
  -> scene detection
  -> scene MaxSCL / AverageMaxRGB / HDR10+ luminance distributions
  -> ST-2094-40 Profile-A hdr10plus.json
```

The generator does not inject metadata, remux files or replace sources.
DragonTools keeps those transactional steps in its existing `hdr10plus_tool`
pipeline.

## Analysis model

Every video frame is decoded so scene/frame alignment stays exact. For speed the
analysis image is spatially reduced (default width 256 pixels, aspect ratio
preserved). The generator derives linearized maxRGB statistics from PQ RGB:

- MaxSCL per RGB channel
- AverageRGB / AverageMaxRGB
- 1%, 25%, 50%, 75%, 90%, 95%, 99.98% percentiles
- DistributionY99 from the per-frame 99.99% percentile
- DistributionY100nit from the percentage of pixels <= 100 nits
- histogram-based scene boundaries

The emitted classic JSON uses the canonical distribution indices
`[1,5,10,25,50,75,90,95,99]` and luminance values in 0.1 nit units as expected
by `hdr10plus_tool`.

Profile A is intentional: the generator emits measured dynamic luminance
metadata but does not invent Profile-B knee points or Bezier tone-mapping
curves. Tone mapping remains display-side.

## Optional tuning

```text
--ffmpeg <path>
--ffprobe <path>
--analysis-width 256
--scene-threshold 0.32
--min-scene-frames 6
```

Increasing `--analysis-width` improves spatial measurement fidelity at the cost
of analysis time and memory bandwidth. Temporal sampling is never reduced.

## Requirements

- Python 3.11+
- NumPy 2.x
- FFmpeg + ffprobe

`build.bat` checks/installs NumPy and PyInstaller before building the standalone
EXE.
