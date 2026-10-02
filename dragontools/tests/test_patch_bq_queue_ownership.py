from types import SimpleNamespace

from dragontools.core.path_syntax import path_compare_key
from dragontools.worker.converter_queue_state import ConverterQueueState
from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
from dragontools.worker.parallel_converter_state import ParallelQueueState


def test_global_order_cannot_inject_previously_completed_or_foreign_jobs():
    queue = ConverterQueueState(['episode09.mkv'])
    queue.next_file(0)
    queue.reorder_waiting_files(['episode02.mkv', 'episode03.mkv',
                                 'episode09.mkv', 'next.mkv'])
    queue.complete_current('episode09.mkv')
    assert queue.next_file(1) is None


def test_reorder_keeps_owned_waiting_jobs_and_canonical_paths():
    queue = ConverterQueueState(['current.mkv', 'First.mkv', 'second.mkv'])
    queue.next_file(0)
    queue.reorder_waiting_files(['SECOND.MKV', 'second.mkv', 'foreign.mkv'])
    assert queue.files == ['second.mkv', 'First.mkv']
    queue.complete_current('current.mkv')
    assert queue.next_file(1)[0] == 'second.mkv'
    queue.complete_current('second.mkv')
    assert queue.next_file(2)[0] == 'First.mkv'
    queue.complete_current('First.mkv')
    assert queue.next_file(3) is None


def test_empty_or_stale_order_does_not_drop_live_added_file():
    queue = ConverterQueueState(['current.mkv'])
    queue.next_file(0)
    assert queue.add_file('new.mkv', lambda *_: None)
    queue.reorder_waiting_files([])
    queue.complete_current('current.mkv')
    assert path_compare_key(queue.next_file(1)[0]) == path_compare_key('new.mkv')


def test_reorder_does_not_restore_done_or_skipped_jobs():
    queue = ConverterQueueState(['done.mkv', 'skip.mkv', 'waiting.mkv'])
    queue.done_files.add('done.mkv')
    queue.skip_files.add('skip.mkv')
    queue.reorder_waiting_files(['done.mkv', 'skip.mkv', 'waiting.mkv'])
    assert queue.files == ['waiting.mkv']


def test_parent_filters_global_order_by_worker_ownership():
    calls_a, calls_b = [], []
    a = SimpleNamespace(reorder_waiting_files=calls_a.append)
    b = SimpleNamespace(reorder_waiting_files=calls_b.append)
    state = ParallelQueueState(['a.mkv', 'b.mkv', 'pending.mkv'])
    owner = SimpleNamespace(
        _queue_state=state, _workers=[a, b],
        _assigned={path_compare_key('a.mkv'): a, path_compare_key('b.mkv'): b},
        _sync_child_display_positions=lambda: None,
        _emit_aggregate_progress=lambda: None,
    )
    ParallelConverterQueueMixin.reorder_waiting_files(
        owner, ['pending.mkv', 'b.mkv', 'a.mkv'])
    assert calls_a == [['a.mkv']]
    assert calls_b == [['b.mkv']]


def test_dv_postprocessing_child_cannot_take_next_encode_job():
    old = ConverterQueueState(['dv.mkv'])
    old.next_file(0)
    new = ConverterQueueState(['next.mkv'])
    new.next_file(0)
    for _ in range(3):
        old.reorder_waiting_files(['completed.mkv', 'dv.mkv', 'next.mkv'])
        new.reorder_waiting_files(['completed.mkv', 'dv.mkv', 'next.mkv'])
    old.complete_current('dv.mkv')
    new.complete_current('next.mkv')
    assert old.next_file(1) is None
    assert new.next_file(1) is None
