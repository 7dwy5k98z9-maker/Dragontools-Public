# -*- coding: utf-8 -*-
"""
dragontools/core/gpu_detection.py

Qt-unabhängige GPU-Erkennung für automatische Encoder-Wahl.
Erkennt: NVIDIA (NVENC), Intel (QSV), AMD (AMF).

Windows: liest GPU-Namen direkt aus der Windows-Registry (winreg) –
         KEIN subprocess, KEIN wmic, KEINE Konsolenfenster.
Linux:   lspci (subprocess, nur auf Linux relevant).
"""
from __future__ import annotations
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class GpuInfo:
    name: str
    vendor: str          # "nvidia" | "intel" | "amd" | "unknown"
    encoder: str         # "nvenc"  | "qsv"   | "amf"  | "cpu"
    is_igpu: bool        # True = integrierte GPU


def _is_igpu(name: str) -> bool:
    name_l = name.lower()
    return any(k in name_l for k in (
        "intel", "uhd", "iris", "hd graphics", "vega", "radeon rx vega",
        "amd radeon(tm)", "ryzen"
    ))


_gpu_cache: list[GpuInfo] | None = None


def detect_gpus() -> list[GpuInfo]:
    """Gibt eine Liste aller erkannten GPUs zurück.

    Das Ergebnis wird gecacht – Erkennung läuft nur einmal pro Sitzung.
    Auf Windows wird ausschließlich winreg verwendet (kein subprocess/wmic).
    """
    global _gpu_cache
    if _gpu_cache is not None:
        return _gpu_cache

    if sys.platform == "win32":
        _gpu_cache = _detect_windows()
    else:
        _gpu_cache = _detect_linux()

    return _gpu_cache


def _detect_windows() -> list[GpuInfo]:
    """Liest GPU-Namen aus der Windows-Registry.

    Pfad: HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-...}
    Jeder Unterschlüssel mit vierstelligem Namen (0000, 0001 ...) repraesentiert
    einen Display-Adapter. Der Wert 'DriverDesc' enthält den GPU-Namen.

    Kein subprocess, kein wmic – keine Konsolenfenster.
    """
    gpus: list[GpuInfo] = []
    try:
        import winreg

        DISPLAY_CLASS = "{4d36e968-e325-11ce-bfc1-08002be10318}"
        key_path = rf"SYSTEM\CurrentControlSet\Control\Class\{DISPLAY_CLASS}"

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
            idx = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base_key, idx)
                    idx += 1

                    # Nur vierstellige Adapter-Schlüssel (0000, 0001, ...)
                    if not subkey_name.isdigit():
                        continue

                    with winreg.OpenKey(base_key, subkey_name) as adapter_key:
                        try:
                            name = winreg.QueryValueEx(adapter_key, "DriverDesc")[0]
                        except OSError:
                            continue

                    name = str(name).strip()
                    if not name:
                        continue

                    nl = name.lower()
                    if "nvidia" in nl:
                        vendor, encoder = "nvidia", "nvenc"
                    elif "intel" in nl:
                        vendor, encoder = "intel", "qsv"
                    elif "amd" in nl or "radeon" in nl:
                        vendor, encoder = "amd", "amf"
                    else:
                        vendor, encoder = "unknown", "cpu"

                    gpus.append(GpuInfo(
                        name=name,
                        vendor=vendor,
                        encoder=encoder,
                        is_igpu=_is_igpu(name),
                    ))

                except OSError:
                    # EnumKey wirft OSError wenn keine weiteren Schlüssel vorhanden
                    break

    except Exception:
        pass

    return gpus


def _detect_linux() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    try:
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            ll = line.lower()
            if not any(k in ll for k in ("vga", "3d", "display")):
                continue
            if "nvidia" in ll:
                vendor, encoder = "nvidia", "nvenc"
            elif "intel" in ll:
                vendor, encoder = "intel", "qsv"
            elif "amd" in ll or "radeon" in ll or "advanced micro" in ll:
                vendor, encoder = "amd", "amf"
            else:
                vendor, encoder = "unknown", "cpu"
            name = line.split(":", 2)[-1].strip()
            gpus.append(GpuInfo(name=name, vendor=vendor, encoder=encoder, is_igpu=_is_igpu(name)))
    except Exception:
        pass
    return gpus


def best_encoder() -> str:
    """
    Wählt den besten verfügbaren Encoder.
    Reihenfolge: dGPU NVIDIA > dGPU AMD > dGPU Intel > iGPU > CPU
    """
    gpus = detect_gpus()
    if not gpus:
        return "cpu"

    dgpus = [g for g in gpus if not g.is_igpu]
    igpus = [g for g in gpus if g.is_igpu]

    for pool in (dgpus, igpus):
        for vendor in ("nvidia", "amd", "intel"):
            for g in pool:
                if g.vendor == vendor:
                    return g.encoder

    return "cpu"


def gpu_summary() -> str:
    """Kurze lesbare Zusammenfassung für den Einstellungs-Dialog."""
    gpus = detect_gpus()
    if not gpus:
        return "Keine GPU erkannt – CPU-Encoding wird verwendet."
    lines = []
    for g in gpus:
        tag = " (integriert)" if g.is_igpu else " (dediziert)"
        lines.append(f"• {g.name}{tag} → {g.encoder.upper()}")
    best = best_encoder()
    lines.append(f"\n➜ Automatische Wahl: {best.upper()}")
    return "\n".join(lines)
