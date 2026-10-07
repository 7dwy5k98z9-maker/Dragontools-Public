"""Crash-marker filenames shared by recovery, cleanup and support export."""
import re


def is_crash_state_file(path):
    return path.name == "crash_state.json" or re.fullmatch(r"crash_state_\d+\.json", path.name) is not None
