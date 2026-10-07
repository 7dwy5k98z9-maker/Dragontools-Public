"""One GPAC argv boundary for audio labels/defaults and timed-text roles."""
from pathlib import Path


def mp4box_track_argument(path, *, language='und', title='', default=None, forced_subtitle=False, media_type=None):
    selector = '#audio' if media_type=='audio' else ''
    argument = f'{path}{selector}:lang={str(language or "und").strip().lower()}'
    if forced_subtitle:
        # tx3g flags provide player signalling; the ISO kind role is also
        # needed by FFmpeg's MP4 demuxer to expose disposition.forced.
        argument += ':hdlr=text:txtflags=0xC0000000'
    if default is not None and not bool(default):
        argument += ':disable'
    label = str(title or '').replace('"', "'").strip()
    if forced_subtitle and 'forced' not in label.lower():
        label = f'{label} [Forced]'.strip() if label else 'Forced'
    if label:
        # No shell is used: quoting a label here stores literal quote characters.
        argument += f':name={label}'
    return argument


def append_mp4box_subtitle(command, track):
    if getattr(track,'source_direct',False) or Path(track.path).suffix.casefold() not in {'.srt','.ttxt'}:
        raise ValueError('MP4-Untertitel benötigen eine vorbereitete einzelne Textspur; ganze Quellcontainer sind gesperrt.')
    # These mux commands add exactly one prepared video/audio/subtitle per
    # import. Assign the output ID explicitly; it is never a source stream ID.
    track_id = command.count('-add') + 1
    argument = mp4box_track_argument(track.path, language=track.language, title=track.title,
        default=bool(getattr(track,'default',False)), forced_subtitle=bool(track.forced))
    command += ['-add', argument+f':ID={track_id}']
    if track.forced:
        # Import options split on colons, so a URN cannot be an inline kind
        # value. The separate GPAC option preserves the complete scheme URI.
        command += ['-kind', f'{track_id}=urn:mpeg:dash:role:2011=forced-subtitle']
