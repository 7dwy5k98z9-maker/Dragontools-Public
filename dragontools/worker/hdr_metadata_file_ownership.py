"""Keep metadata-tool outputs distinct from every source file."""
from pathlib import Path


def metadata_output_conflicts_with_sources(output, *sources):
    target = Path(output)
    try:
        for source in sources:
            if source is None:
                continue
            original = Path(source)
            if target.resolve(strict=False) == original.resolve(strict=False):
                return True
            if target.exists() and original.exists() and target.samefile(original):
                return True
        return False
    except OSError:
        # An unresolved identity is not permission to unlink a possible source.
        return True
