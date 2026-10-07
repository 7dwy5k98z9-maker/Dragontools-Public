"""Conservative canonical movie identity shared by matching and replacement."""
from __future__ import annotations
from dataclasses import dataclass, replace
from pathlib import Path
import re, unicodedata
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

def normalize_movie_title(value: str) -> str:
    text=unicodedata.normalize('NFC',str(value or '')).casefold()
    text=text.translate(str.maketrans({'–':'-','—':'-','−':'-','‐':'-','‑':'-',
        '’':"'",'‘':"'",'ʼ':"'",'\u00a0':' '}))
    from ..rules.renamer_rules import sanitize_renamer_text
    text=sanitize_renamer_text(text)
    text=re.sub(r'\s*-\s*','-',text)
    return re.sub(r'\s+',' ',text).strip()

@dataclass(frozen=True)
class MovieIdentity:
    normalized_title: str
    year: int | None
    edition: str = ''
    metadata_ids: tuple[tuple[str,str], ...] = ()

    def matches(self, other: 'MovieIdentity') -> bool:
        if self.year is not None and other.year is not None and self.year!=other.year:
            return False
        if self.edition!=other.edition:
            return False
        left,right=dict(self.metadata_ids),dict(other.metadata_ids)
        shared=left.keys() & right.keys()
        if shared:
            return all(left[key]==right[key] for key in shared)
        return self.year is not None and self.year==other.year and self.normalized_title==other.normalized_title

def movie_identity_for_name(stem: str) -> MovieIdentity:
    text=normalize_movie_title(stem)
    year_match=re.search(r'\((18\d{2}|19\d{2}|20\d{2}|21\d{2})\)',text)
    identity=MovieIdentity(text[:year_match.start()].strip() if year_match else text,
        int(year_match[1]) if year_match else None,text[year_match.end():].strip() if year_match else '')
    return identity

def movie_identity_for_path(path: Path, *, metadata_path: Path | None = None) -> MovieIdentity:
    path=Path(path)
    identity=movie_identity_for_name(path.stem)
    nfo=(metadata_path or path).with_suffix('.nfo')
    if not nfo.exists():
        folder=(metadata_path or path).parent
        common=folder/'movie.nfo'
        from .path_syntax import VIDEO_EXTENSIONS
        videos=[p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in VIDEO_EXTENSIONS] if folder.exists() else []
        if len(videos)!=1 or not common.exists():
            return identity
        nfo=common
    return replace(identity, metadata_ids=_read_movie_ids(nfo))

def _read_movie_ids(nfo: Path) -> tuple[tuple[str, str], ...]:
    """Read bounded, unambiguous metadata independently of title parsing."""
    try:
        if nfo.stat().st_size>1024*1024:
            raise ValueError('Film-NFO ist zu groß für eine sichere Identitätsprüfung.')
        root=ET.parse(nfo).getroot()
        if root.tag!='movie':
            raise ValueError('NFO bestätigt keine Filmidentität.')
        ids={}
        for node in root.findall('uniqueid'):
            provider=str(node.get('type','')).strip().casefold()
            value=str(node.text or '').strip()
            if provider and value:
                if provider in ids and ids[provider]!=value:
                    raise ValueError('Widersprüchliche Metadata-IDs in Film-NFO.')
                ids[provider]=value
        for tag,provider in [('tmdbid','tmdb'),('imdbid','imdb')]:
            value=str(root.findtext(tag) or '').strip()
            if value:
                if provider in ids and ids[provider]!=value:
                    raise ValueError('Widersprüchliche Metadata-IDs in Film-NFO.')
                ids[provider]=value
        return tuple(sorted(ids.items()))
    except (OSError,ET.ParseError,DefusedXmlException) as exc:
        raise ValueError(f'Filmidentität aus NFO nicht sicher lesbar: {nfo.name}') from exc

def find_movie_identity_conflicts(dst_p: Path, src_p: Path | None = None) -> list[Path]:
    from .move_conflicts import VIDEO_SUFFIXES,episode_identity_for_path,same_path
    dst_p=Path(dst_p)
    if dst_p.suffix.casefold() not in VIDEO_SUFFIXES or episode_identity_for_path(dst_p):
        return []
    identity=movie_identity_for_path(dst_p,metadata_path=Path(src_p) if src_p else None)
    if not dst_p.parent.exists():
        return []
    matches=[]
    for candidate in sorted(dst_p.parent.iterdir()):
        if not candidate.is_file() or candidate.suffix.casefold() not in VIDEO_SUFFIXES:
            continue
        if (src_p and same_path(candidate,src_p)) or episode_identity_for_path(candidate):
            continue
        if identity.matches(movie_identity_for_path(candidate)):
            matches.append(candidate)
    return matches

def find_movie_replacement_artifacts(dst_p: Path, conflicts: list[Path]) -> list[Path]:
    from .move_conflicts import EPISODE_REPLACEMENT_ARTIFACT_SUFFIXES
    stems=[path.stem.casefold() for path in conflicts]
    artifacts=sorted(p for p in Path(dst_p).parent.iterdir()
        if p.suffix.casefold() in EPISODE_REPLACEMENT_ARTIFACT_SUFFIXES
        and any(p.stem.casefold()==stem or p.name.casefold().startswith(stem+'.') for stem in stems)
        and (p.is_file() or p.suffix.casefold()=='.trickplay' and p.is_dir()))
    from .path_syntax import VIDEO_EXTENSIONS
    folder=Path(dst_p).parent
    videos={p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in VIDEO_EXTENSIONS}
    common=folder/'movie.nfo'
    if len(conflicts)==1 and videos==set(conflicts) and common.is_file() and common not in artifacts:
        artifacts.append(common)
    return sorted(artifacts)
