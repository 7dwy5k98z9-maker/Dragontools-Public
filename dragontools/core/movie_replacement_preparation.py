"""Identity approval and companion receipts for transactional movie replacement."""
from __future__ import annotations
import os
from .movie_identity import find_movie_identity_conflicts,find_movie_replacement_artifacts,movie_identity_for_path
from .transaction_identity import path_receipt,receipt_matches
from .move_conflicts import VIDEO_SUFFIXES,episode_identity_for_path

def validate_movie_replacement(src_p,dst_p,conflicts):
    movie_conflicts=find_movie_identity_conflicts(dst_p,src_p)
    if len(movie_conflicts)>1:
        return 'Mehrdeutige Filmidentität: vorhandene Versionen bleiben erhalten.',movie_conflicts
    if dst_p.suffix.casefold() not in VIDEO_SUFFIXES or episode_identity_for_path(dst_p):
        return '',[]
    desired=movie_identity_for_path(dst_p,metadata_path=src_p)
    for candidate in conflicts:
        left,right=dict(desired.metadata_ids),dict(movie_identity_for_path(candidate).metadata_ids)
        if any(left[k]!=right[k] for k in left.keys() & right.keys()):
            return 'Widersprüchliche Film-Metadata-IDs; Ziel bleibt erhalten.',movie_conflicts
    return '',movie_conflicts

def approve_movie_replacement(prepared,src_p,dst_p,conflicts):
    if not conflicts:
        return
    artifacts=find_movie_replacement_artifacts(dst_p,conflicts)
    prepared['movie_replacement_preapproved']=True
    prepared['approved_movie_identity']=movie_identity_for_path(dst_p,metadata_path=src_p)
    prepared['approved_artifacts']={str(path):path_receipt(path) for path in artifacts}

def movie_commit_artifacts(prepared,src_p,dst_p,protected_paths):
    if not prepared.get('movie_replacement_preapproved'):
        return []
    conflicts=find_movie_identity_conflicts(dst_p,src_p)
    if len(conflicts)!=1 or movie_identity_for_path(dst_p,metadata_path=src_p)!=prepared['approved_movie_identity']:
        raise ValueError('Filmidentität änderte sich nach der Vorbereitung; Altbestand bleibt erhalten.')
    protected={os.path.normcase(os.path.abspath(str(p))) for p in protected_paths or ()}
    artifacts=[p for p in find_movie_replacement_artifacts(dst_p,conflicts)
        if os.path.normcase(os.path.abspath(str(p))) not in protected]
    if any(not receipt_matches(p,prepared.get('approved_artifacts',{}).get(str(p))) for p in artifacts):
        raise ValueError('Film-Companions änderten sich nach der Vorbereitung.')
    return artifacts
