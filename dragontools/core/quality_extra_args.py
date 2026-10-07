"""Parse direct FFmpeg argv using the host's quoting rules."""
import os
import shlex


def split_quality_extra_args(text):
    raw = str(text or '').strip()
    if not raw:
        return []
    if os.name != 'nt':
        return shlex.split(raw, posix=True)
    import ctypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    parse = shell.CommandLineToArgvW
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    arguments = parse('ffmpeg.exe ' + raw, ctypes.byref(count))
    if not arguments:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [arguments[i] for i in range(1, count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(arguments, ctypes.c_void_p))
