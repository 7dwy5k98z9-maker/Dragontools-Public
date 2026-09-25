"""Reject external media tools in a public application folder or release ZIP."""
import sys
import zipfile
from pathlib import Path

TOOLS = {'ffmpeg.exe', 'ffprobe.exe', 'mp4box.exe', 'dovi_tool.exe',
         'hdr10plus_tool.exe', 'mediainfo.exe', 'handbrake.exe', 'handbrakecli.exe',
         'mkvmerge.exe', 'mkvextract.exe', 'mkvinfo.exe', 'mkvpropedit.exe',
         'mkvtoolnix-gui.exe', 'makemkv.exe', 'makemkvcon.exe', 'makemkvcon64.exe',
         'renamemytvseries.exe'}

def check(path):
    path = Path(path)
    if path.is_dir():
        names = [p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()]
    else:
        with zipfile.ZipFile(path) as archive:
            names = [i.filename for i in archive.infolist() if not i.is_dir()]
    bad = [n for n in names if set(n.lower().split('/')) & {'programme', 'third_party'}
           or n.lower().split('/')[-1] in TOOLS]
    if not any(n.endswith('TOOLS_INSTALLIEREN.txt') for n in names):
        bad.append('TOOLS_INSTALLIEREN.txt fehlt')
    if bad:
        raise ValueError('Public-Paket unzulaessig: ' + ', '.join(bad[:15]))
    return len(names)

if __name__ == '__main__':
    print(f'Public-Paket geprueft: {check(sys.argv[1])} Dateien, keine externen Medienwerkzeuge.')
