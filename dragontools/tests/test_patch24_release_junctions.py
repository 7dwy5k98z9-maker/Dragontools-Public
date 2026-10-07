import sys
import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows junction contract')
@pytest.mark.parametrize('operation', ['source_zip', 'snapshot'])
def test_release_inventory_rejects_junction_to_foreign_directory(tmp_path, operation):
    import _winapi
    from dragontools.core.release_packaging import create_source_release_zip
    from extras.snapshot_manifest import build_snapshot_manifest
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'module.py').write_text('VALUE=1\n', encoding='utf-8')
    foreign = tmp_path / 'private'
    foreign.mkdir()
    (foreign / 'foreign.dat').write_bytes(b'foreign confidential data')
    junction = root / 'config'
    _winapi.CreateJunction(str(foreign), str(junction))
    try:
        with pytest.raises(RuntimeError):
            if operation == 'source_zip':
                create_source_release_zip(root, tmp_path / 'release.zip')
            else:
                build_snapshot_manifest(root)
        assert (foreign / 'foreign.dat').read_bytes() == b'foreign confidential data'
    finally:
        junction.rmdir()
