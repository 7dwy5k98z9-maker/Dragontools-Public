"""Readable document evidence includes relationships, XMP and annotations."""
from defusedxml.ElementTree import fromstring
import zipfile


def xml_searchable_text(data):
    root = fromstring(data)
    attributes = [value for node in root.iter() for value in node.attrib.values()]
    paragraphs = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'p']
    text = [''.join(node.itertext()) for node in paragraphs] if paragraphs else [''.join(root.itertext())]
    return '\n'.join(text + attributes)


def docx_searchable_text(path):
    with zipfile.ZipFile(path) as archive:
        return '\n'.join(xml_searchable_text(archive.read(name)) for name in archive.namelist()
            if name.casefold().endswith(('.xml', '.rels')))


def _annotation_strings(value, seen=None):
    seen = set() if seen is None else seen
    value = value.get_object() if hasattr(value, 'get_object') else value
    identity = id(value)
    if identity in seen:
        return []
    seen.add(identity)
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() if key not in {'/P', '/Parent'}
            for text in _annotation_strings(item, seen)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _annotation_strings(item, seen)]
    return []


def pdf_hidden_text(reader):
    chunks = []
    metadata = reader.trailer['/Root'].get('/Metadata')
    if metadata is not None:
        chunks.append(xml_searchable_text(metadata.get_object().get_data()))
    for page in reader.pages:
        for annotation in page.get('/Annots') or []:
            chunks.extend(_annotation_strings(annotation))
    return '\n'.join(chunks)
