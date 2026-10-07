"""Bind a time model to the two files it actually analyzed."""
from .path_syntax import path_compare_key
from .transaction_identity import stat_identity


def require_mapping_inputs(mapping, source_path, target_path):
    for info, path in ((mapping.source_info, source_path), (mapping.target_info, target_path)):
        if path_compare_key(info.path) != path_compare_key(path):
            raise RuntimeError("Analyse gehört zu einer anderen Datei; bitte erneut analysieren.")
        identity = getattr(info, 'file_identity', None)
        if identity is not None and list(identity) != stat_identity(path):
            raise RuntimeError("Analysierte Datei wurde verändert; bitte erneut analysieren.")
