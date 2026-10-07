from pathlib import Path
import json
import zipfile

import pytest


def secret():
    # A deliberately fabricated token; never include it in failure details.
    return 'synthetic_' + 'a9b8c7d6e5f40123456789'


@pytest.mark.parametrize('style', ['json', 'private_then_secret', 'unquoted_env'])
def test_source_release_rejects_secret_in_supported_text_syntax(tmp_path, style):
    from dragontools.core.release_packaging import create_source_release_zip
    root=tmp_path/'project'; root.mkdir()
    value=secret()
    text=json.dumps({'api_key':value}) if style=='json' else 'api_key="'+value+'"'
    if style=='private_then_secret': text='C:\\Users'+'\\PrivatePerson\\Videos\n'+text
    if style=='unquoted_env': text='API_KEY='+value+'\n'
    (root/'settings.txt').write_text(text,encoding='utf-8')
    target=tmp_path/'release.zip'; target.write_bytes(b'previous')
    with pytest.raises(RuntimeError): create_source_release_zip(root,target)
    assert target.read_bytes()==b'previous'


def test_privacy_error_details_never_repeat_secret_value(tmp_path):
    from dragontools.core.release_validation_privacy import _scan_private_markers
    value=secret(); (tmp_path/'config.txt').write_text('api_key="'+value+'"',encoding='utf-8')
    checks=_scan_private_markers(tmp_path)
    errors=[c for c in checks if c.status=='error']
    assert errors and all(value not in c.detail for c in errors)


@pytest.mark.parametrize('relative',['.env','.env.local','config/credentials.json','config/private.key',
    'config/session.sqlite3','worker/recovery.zip','config/id_rsa'])
def test_public_inventory_never_includes_local_credentials_or_archives(tmp_path,relative):
    from dragontools.core.release_packaging import create_source_release_zip
    (tmp_path/'module.py').write_text('VALUE=1\n',encoding='utf-8')
    path=tmp_path/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'private-local-data')
    out=tmp_path.parent/(tmp_path.name+'-source.zip')
    create_source_release_zip(tmp_path,out)
    with zipfile.ZipFile(out) as z:
        assert relative not in z.namelist() and 'module.py' in z.namelist()


def test_docx_private_link_target_is_checked(tmp_path):
    from dragontools.core.release_validation_privacy import _scan_private_markers
    with zipfile.ZipFile(tmp_path/'manual.docx','w') as z:
        z.writestr('word/_rels/document.xml.rels',
            '<Relationships><Relationship Target="file:///C:/Users/'+'PrivatePerson/secret.docx" /></Relationships>')
        z.writestr('word/document.xml','<document><text>Public manual</text></document>')
    assert any(c.status=='error' and 'DOCX' in c.title for c in _scan_private_markers(tmp_path))


def test_docx_split_runs_do_not_hide_private_names(tmp_path):
    from dragontools.core.release_validation_privacy import _scan_private_markers
    with zipfile.ZipFile(tmp_path/'manual.docx','w') as z:
        z.writestr('word/document.xml','<document><t>Mar</t><t>kus Developer</t></document>')
    assert any(c.status=='error' and 'DOCX' in c.title for c in _scan_private_markers(tmp_path))


def test_pdf_link_annotation_private_target_is_checked(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,TextStringObject,ArrayObject,NumberObject
    from dragontools.core.release_validation_privacy import _scan_private_markers
    writer=PdfWriter(); page=writer.add_blank_page(72,72)
    action=DictionaryObject({NameObject('/S'):NameObject('/URI'),
        NameObject('/URI'):TextStringObject('file:///C:/Users/'+'PrivatePerson/file.txt')})
    link=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
        NameObject('/Rect'):ArrayObject([NumberObject(n) for n in [0,0,30,30]]),NameObject('/A'):action})
    page[NameObject('/Annots')]=ArrayObject([writer._add_object(link)])
    writer.write(tmp_path/'manual.pdf')
    assert any(c.status=='error' and 'PDF' in c.title for c in _scan_private_markers(tmp_path))


def test_source_archive_cannot_replace_a_source_file(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip
    code=tmp_path/'module.py'; code.write_text('VALUE=1\n',encoding='utf-8')
    with pytest.raises((ValueError,RuntimeError)):
        create_source_release_zip(tmp_path,code)
    assert code.read_text(encoding='utf-8')=='VALUE=1\n'


def test_source_archive_unchanged_destination_is_required_before_commit(tmp_path,monkeypatch):
    from dragontools.core import release_packaging as module
    root=tmp_path/'project'; root.mkdir(); (root/'module.py').write_text('VALUE=1\n')
    target=tmp_path/'release.zip'; target.write_bytes(b'previous')
    original=module._write_public_member
    def write(*a,**k):
        original(*a,**k); target.write_bytes(b'foreign change')
    monkeypatch.setattr(module,'_write_public_member',write)
    with pytest.raises((OSError,RuntimeError)): module.create_source_release_zip(root,target)
    assert target.read_bytes()==b'foreign change'


def test_source_archive_rejects_member_changed_after_privacy_scan(tmp_path,monkeypatch):
    from dragontools.core import release_packaging as module
    from dragontools.core import release_validation_privacy as privacy
    root=tmp_path/'project'; root.mkdir(); code=root/'module.py'; code.write_text('VALUE=1\n')
    original=privacy._scan_private_markers
    def scan(*a,**k):
        checks=original(*a,**k); code.write_text('API_KEY="'+secret()+'"\n'); return checks
    monkeypatch.setattr(privacy,'_scan_private_markers',scan)
    out=tmp_path/'release.zip'
    with pytest.raises((OSError,RuntimeError)): module.create_source_release_zip(root,out)
    assert not out.exists()


@pytest.mark.parametrize('version',['9.9.0-rc..1','9.9.0-rc.01','9.9.0+build..1','09.9.0','9.09.0'])
def test_update_version_rejects_invalid_identifiers(version):
    from dragontools.core.update_check import version_tuple
    with pytest.raises(ValueError): version_tuple(version)


def test_prerelease_text_uses_ascii_case_sensitive_order():
    from dragontools.core.update_check import is_newer_version
    assert is_newer_version('9.9.0-alpha','9.9.0-Alpha')
    assert not is_newer_version('9.9.0-Alpha','9.9.0-alpha')


@pytest.mark.parametrize('flag',['draft','prerelease'])
def test_latest_stable_update_rejects_draft_and_prerelease_payload(flag):
    from dragontools.core.update_check import parse_release_response
    result=parse_release_response(json.dumps({'tag_name':'v10.0.0',flag:True}),'9.9.0')
    assert not result.ok and not result.update_available


def test_update_link_is_bound_to_the_configured_repository():
    from dragontools.core.update_check import parse_release_response,UPDATE_RELEASES_URL
    value=parse_release_response(json.dumps({'tag_name':'v10.0.0',
        'html_url':'https://github.com/unrelated/downloads/releases/tag/v10.0.0'}),'9.9.0')
    assert value.release.page_url==UPDATE_RELEASES_URL


@pytest.mark.parametrize('version',[{},[], ['1'], 'bogus', True, 1.0])
def test_invalid_manifest_schema_returns_error_instead_of_crashing(tmp_path,version):
    from dragontools.core.release_validation_package import _load_release_manifest
    (tmp_path/'release_manifest.json').write_text(json.dumps({'schema_version':version,'profile':'source-only','app_version':'9.9.0'}),encoding='utf-8')
    _data,check=_load_release_manifest(tmp_path)
    assert check.status=='error'


def test_whisper_versions_have_reproducible_bounds_too(tmp_path):
    from dragontools.core.release_validation_environment import _check_optional_environment
    (tmp_path/'requirements-optional.txt').write_text('numpy>=1,<3\nopencv-python-headless>=4,<5\n-r requirements-whisper.txt\n')
    (tmp_path/'requirements-whisper.txt').write_text('faster-whisper>=1.1\nctranslate2>=4.4,<5\n')
    result=_check_optional_environment(tmp_path)
    assert result.status=='warn' and 'faster-whisper' in result.detail


@pytest.mark.parametrize('spec',['!=6.0,>=1','===arbitrary','>=6,<6','==*'])
def test_requirement_bound_checker_does_not_accept_invalid_or_empty_range(spec):
    from dragontools.core.release_validation_environment import _has_reproducible_bound
    assert not _has_reproducible_bound(spec)


def test_build_smoke_includes_new_worker_and_metadata_modules():
    from dragontools.core.release_validation_package import _SMOKE_MODULES
    expected={'gui/file_worker_pause.py','core/owned_process_pause.py','worker/audio_video_output_contract.py',
        'gui/quality_worker_lifecycle.py','core/quality_extra_args.py','gui/dialog_ownership.py',
        'worker/comfyui_video_contract.py','worker/postprocess_metadata_identity.py'}
    assert expected <= {p.as_posix() for p in _SMOKE_MODULES}


@pytest.mark.parametrize('payload',['[]','null','"text"','false'])
def test_snapshot_verifier_reports_malformed_top_level_without_crashing(tmp_path,payload):
    from extras.snapshot_manifest import verify_snapshot_manifest
    (tmp_path/'SNAPSHOT_CONTENTS.json').write_text(payload,encoding='utf-8')
    assert verify_snapshot_manifest(tmp_path)


def test_docx_active_metadata_version_must_match_release(tmp_path):
    from dragontools.core.release_validation_source import _check_release_version_references
    from dragontools.core.version import APP_VERSION
    for name in ['README.md','PATCH.md','help.html']:
        (tmp_path/name).write_text('DragonTools V'+APP_VERSION,encoding='utf-8')
    history=tmp_path/'Aenderungshistorie'; history.mkdir()
    (history/'CHANGELOG.json').write_text(json.dumps({'current':APP_VERSION}))
    with zipfile.ZipFile(tmp_path/'DragonToolsV9_Dokumentation.docx','w') as z:
        z.writestr('docProps/core.xml','<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
            '<cp:version>'+APP_VERSION+'</cp:version><cp:subject>DragonTools V0.0.1</cp:subject></cp:coreProperties>')
    result=_check_release_version_references(tmp_path)
    assert result.status=='error' and 'subject' in result.detail


def test_runtime_smoke_imports_all_required_modules(monkeypatch):
    from dragontools.core import release_frozen_runtime as module
    from dragontools.core.release_validation_package import _SMOKE_MODULES
    seen=[]; monkeypatch.setattr(module,'import_module',seen.append)
    module.verify_runtime_imports()
    expected=['dragontools.'+(p.parent if p.name=='__init__.py' else p.with_suffix('')).as_posix().replace('/','.') for p in _SMOKE_MODULES]
    assert seen==list(dict.fromkeys(expected))


def test_runtime_smoke_checks_native_quality_widgets_and_jpeg(qapp):
    from dragontools.gui.release_frozen_widgets import verify_native_widgets_and_jpeg
    verify_native_widgets_and_jpeg()
    qapp.processEvents()


@pytest.mark.parametrize('kind', ['docx', 'pdf'])
@pytest.mark.parametrize('syntax', ['json', 'quoted', 'unquoted'])
def test_document_secret_is_rejected_without_echoing_value(tmp_path, kind, syntax):
    from dragontools.core.release_validation_privacy import _scan_private_markers
    value = secret()
    text = json.dumps({'api_key': value}) if syntax == 'json' else 'api_key=' + (
        '"' + value + '"' if syntax == 'quoted' else value)
    if kind == 'docx':
        from xml.sax.saxutils import escape
        with zipfile.ZipFile(tmp_path / 'manual.docx', 'w') as archive:
            archive.writestr('word/document.xml', '<document><p>' + escape(text) + '</p></document>')
    else:
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(72, 72)
        writer.add_metadata({'/Subject': text})
        writer.write(tmp_path / 'manual.pdf')
    errors = [check for check in _scan_private_markers(tmp_path) if check.status == 'error']
    assert errors and all(value not in check.detail for check in errors)


def test_runtime_smoke_imports_package_without_init_alias(monkeypatch):
    from dragontools.core import release_frozen_runtime as module
    from dragontools.core import release_validation_package as package
    monkeypatch.setattr(package, '_SMOKE_MODULES', [Path('gui/settings_sections/__init__.py')])
    seen=[]
    monkeypatch.setattr(module, 'import_module', seen.append)
    module.verify_runtime_imports()
    assert seen==['dragontools.gui.settings_sections']


def test_incomplete_source_validation_reports_inventory_error(tmp_path):
    from dragontools.core.release_validation import validate_release
    (tmp_path/'dragontools').mkdir()
    (tmp_path/'build_v9.bat').write_text('echo build\n',encoding='utf-8')
    checks=validate_release(tmp_path,mode='source')
    assert any(c.status=='error' and 'Inventar' in c.title for c in checks)


def test_public_release_requires_native_builder_dependency(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip
    from dragontools.core.release_packaging import PUBLIC_SOURCE_REQUIRED_DIRS, PUBLIC_SOURCE_REQUIRED_ROOT_FILES
    root=tmp_path/'project'; root.mkdir()
    for name in PUBLIC_SOURCE_REQUIRED_DIRS:
        (root/name).mkdir(parents=True,exist_ok=True)
    for name in PUBLIC_SOURCE_REQUIRED_ROOT_FILES:
        path=root/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('public\n',encoding='utf-8')
    (root/'build_v9.bat').write_text('python -m extras.release_pyinstaller DragonToolsV9.py\n',encoding='utf-8')
    target=tmp_path/'release.zip'; target.write_bytes(b'previous release')
    with pytest.raises(FileNotFoundError,match='release_pyinstaller'):
        create_source_release_zip(root,target)
    assert target.read_bytes()==b'previous release'


@pytest.mark.parametrize('kind',['default_python','password_python','password_text'])
def test_source_release_rejects_default_token_and_short_password_literals(tmp_path,kind):
    from dragontools.core.release_packaging import create_source_release_zip
    value=secret() if kind=='default_python' else 'Q9r8'+'T7s6'
    name='DEFAULT_API_KEY' if kind=='default_python' else 'PASSWORD'
    file=tmp_path/('module.py' if kind.endswith('python') else 'settings.txt')
    file.write_text(name+'="'+value+'"\n',encoding='utf-8')
    target=tmp_path.parent/(tmp_path.name+'-release.zip')
    target.write_bytes(b'previous release')
    with pytest.raises(RuntimeError):
        create_source_release_zip(tmp_path,target)
    assert target.read_bytes()==b'previous release'


@pytest.mark.parametrize('syntax',['default_text','prefixed_json'])
def test_source_release_checks_prefixed_credential_names(tmp_path,syntax):
    from dragontools.core.release_packaging import create_source_release_zip
    value=secret()
    text='DEFAULT_API_KEY="'+value+'"' if syntax=='default_text' else json.dumps({'profile_api_key':value})
    (tmp_path/'settings.txt').write_text(text,encoding='utf-8')
    target=tmp_path.parent/(tmp_path.name+'-release.zip'); target.write_bytes(b'previous release')
    with pytest.raises(RuntimeError):
        create_source_release_zip(tmp_path,target)
    assert target.read_bytes()==b'previous release'


@pytest.mark.parametrize('relative',['base_library.zip','certifi/cacert.pem'])
def test_runtime_artifact_scan_accepts_required_public_library_resources(tmp_path,relative):
    from dragontools.core.release_packaging import find_forbidden_release_artifacts
    file=tmp_path/relative; file.parent.mkdir(parents=True,exist_ok=True)
    file.write_bytes(b'public runtime resource')
    assert find_forbidden_release_artifacts(tmp_path)==[]
    assert file.read_bytes()==b'public runtime resource'
