"""Metadata for single-track audio intermediates in both DV MKV mux paths."""


def mkv_audio_track_args(path, metadata, *, language, title):
    args = ['--no-video','--no-subtitles','--no-buttons','--no-attachments',
        '--no-chapters','--no-global-tags','--no-track-tags','--audio-tracks','0',
        '--language', f'0:{language}']
    for key, option in [('default', '--default-track-flag'), ('forced', '--forced-display-flag')]:
        if key in metadata:
            args += [option, f"0:{'yes' if bool(metadata[key]) else 'no'}"]
    if title:
        args += ['--track-name', f'0:{title}']
    return args+[str(path)]
