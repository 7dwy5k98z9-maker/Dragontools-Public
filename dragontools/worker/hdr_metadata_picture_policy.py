"""Reject unsupported changes while carrying image-dependent AV1 metadata."""
from .frame_count_evidence import temporal_mapping_for_filters


def requires_metadata_reauthoring(plan):
    if getattr(plan, 'crop', None):
        return True
    args = list(getattr(plan, 'vf_args', None) or ())
    if temporal_mapping_for_filters(args) != 'preserved':
        return True
    filters = ' '.join(str(args[index + 1]).lower() for index, value in enumerate(args[:-1])
                       if str(value).split(':', 1)[0] in {'-vf', '-filter', '-filter_complex'})
    return any(token in filters for token in (
        'scale=', 'scale_cuda=', 'scale_qsv=', 'crop=', 'transpose=', 'rotate=',
        'hflip', 'vflip', 'pad=', 'tonemap=', 'colorspace=', 'lut=', 'lut3d=',
        'subtitles=', 'ass=', 'overlay=',
    ))
