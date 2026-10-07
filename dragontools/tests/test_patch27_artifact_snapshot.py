"""Nested artifact metadata is owned across terminal snapshot publication."""
from types import SimpleNamespace as NS
import pytest
from dragontools.core.conversion_artifacts import ArtifactRegistry,ConversionArtifactBundle,publish_bundle_to_worker


@pytest.mark.parametrize('ingress',['registry','constructor'])
def test_terminal_bundle_captures_nested_failure_and_postprocess(ingress):
    item={'kind':'nfo','details':{'paths':['old.nfo']}}
    failure={'recovery':{'paths':['candidate.mkv']}}
    if ingress=='registry':
        registry=ArtifactRegistry(postprocess_outputs={'in.mkv':[item]},failure_details={'in.mkv':failure})
        bundle=registry.bundle('in.mkv',status='error')
    else:
        bundle=ConversionArtifactBundle('in.mkv',postprocess=(item,),failure=failure,status='error')
    item['details']['paths'].append('foreign.nfo')
    failure['recovery']['paths'].clear()
    assert bundle.postprocess[0]['details']['paths']==['old.nfo']
    assert bundle.failure['recovery']['paths']==['candidate.mkv']


def test_published_nested_metadata_does_not_mutate_bundle_or_other_receiver():
    bundle=ConversionArtifactBundle('in.mkv',postprocess=({'kind':'nfo','details':{'paths':['out.nfo']}},),
        failure={'recovery':{'paths':['candidate.mkv']}})
    workers=[NS(_sidecar_outputs={},_postprocess_outputs={},_failure_details={}) for _ in range(2)]
    for worker in workers: publish_bundle_to_worker(worker,bundle)
    workers[0]._postprocess_outputs['in.mkv'][0]['details']['paths'].clear()
    workers[0]._failure_details['in.mkv']['recovery']['paths'].append('foreign.mkv')
    assert bundle.postprocess[0]['details']['paths']==['out.nfo']
    assert workers[1]._postprocess_outputs['in.mkv'][0]['details']['paths']==['out.nfo']
    assert bundle.failure['recovery']['paths']==['candidate.mkv']
    assert workers[1]._failure_details['in.mkv']['recovery']['paths']==['candidate.mkv']
