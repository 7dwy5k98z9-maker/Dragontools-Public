from __future__ import annotations

from ..core.timeout_settings import get_timeout


def timeout_hevc_extract() -> int:
    return get_timeout("dv_hevc_extract")


def timeout_dovi_convert() -> int:
    return get_timeout("dv_dovi_convert")


def timeout_rpu_extract() -> int:
    return get_timeout("dv_rpu_extract")



def timeout_dovi_editor() -> int:
    return get_timeout("dv_dovi_editor")


def timeout_rpu_inject() -> int:
    return get_timeout("dv_rpu_inject")


def timeout_mp4box() -> int:
    return get_timeout("dv_mp4box")


def timeout_mkvmerge() -> int:
    return get_timeout("dv_mkvmerge")


def timeout_audio() -> int:
    return get_timeout("dv_audio")


def timeout_encode() -> int:
    return get_timeout("dv_encode")
