"""One CFR eligibility contract for preview, planning and the ComfyUI worker."""
from fractions import Fraction


def source_cfr(media_info) -> Fraction | None:
    video = getattr(media_info, 'primary_video', None)
    if str(getattr(video, 'frame_rate_mode', '') or '').strip().upper() != 'CFR':
        return None
    return positive_fps(getattr(video, 'frame_rate', None))


def positive_fps(value) -> Fraction | None:
    if isinstance(value, bool):
        return None
    try:
        fps = Fraction(str(value or '').strip().replace(',', '.'))
    except (ValueError, ZeroDivisionError):
        return None
    if fps <= 0:
        return None
    # MediaInfo often displays NTSC rates with only three decimal places.
    for numerator in (24000, 30000, 60000, 120000):
        ntsc = Fraction(numerator, 1001)
        if abs(fps - ntsc) < Fraction(1, 1000):
            return ntsc
    return fps
