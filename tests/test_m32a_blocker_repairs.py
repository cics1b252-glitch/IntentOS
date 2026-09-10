"""M32A B1-B6: isolated durability, restart and fail-stop regression evidence."""
import inspect
import json
import os
from pathlib import Path

import pytest

from intent_kernel.rrm.persistence import JsonFileRRMStateStore
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.rrm.models import (
    CapabilityResource, ResourceType, ResourceStatus,
    ConditionalRetirementRequest, ConditionalRetirementOutcome,
    ConditionalReregistrationRequest, ConditionalReregistrationOutcome,
)


def store_at(root):
    return JsonFileRRMStateStore(root / 'rrm/authority.json', root / 'continuity/identity.json')


def retired(tmp_path):
    root = tmp_path / 'install'
    store = store_at(root)
    rrm = RegistryResourceManager(False, store)
    rrm.register_capability(CapabilityResource('c', 'c', governed_registration_id='lineage-A'))
    result = rrm.conditional_retire_resource(ConditionalRetirementRequest(
        ResourceType.CAPABILITY, 'c', 'lineage-A', 1))
    assert result.outcome == ConditionalRetirementOutcome.RETIRED
    request = ConditionalReregistrationRequest(ResourceType.CAPABILITY, 'c', 'lineage-A', 1, 'p', 'd')
    return root, store, rrm, request


def test_r1_r2_default_home_is_isolated(isolated_intent_os_home):
    store = JsonFileRRMStateStore()
    assert store._authority_file == isolated_intent_os_home / 'rrm/authority.json'
    assert store._continuity_file == isolated_intent_os_home / 'continuity/identity.json'
    RegistryResourceManager(False, store)
    assert store._authority_file.is_file()


@pytest.mark.parametrize('operation', ['write', 'unlink', 'rename', 'truncate', 'read'])
def test_r1_real_path_guard_prevents_access_without_touching_files(tmp_path, operation):
    # A fake user home sentinel proves the actual guard, without probing real home.
    from tests import conftest
    sentinel = tmp_path / 'fake-user/.intent-os/rrm/authority.json'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'preserve me')
    before = sentinel.stat()
    old_root = conftest._REAL_INTENT_OS
    conftest._REAL_INTENT_OS = os.path.normcase(str(sentinel.parent.parent))
    try:
        with pytest.raises(RuntimeError, match='real user'):
            if operation == 'write': sentinel.write_bytes(b'bad')
            elif operation == 'unlink': sentinel.unlink()
            elif operation == 'rename': sentinel.rename(sentinel.with_suffix('.moved'))
            elif operation == 'truncate': os.truncate(sentinel, 0)
            else: sentinel.read_bytes()
    finally:
        conftest._REAL_INTENT_OS = old_root
    assert sentinel.read_bytes() == b'preserve me'
    assert sentinel.stat().st_mtime_ns == before.st_mtime_ns


def test_r3_replace_failure_leaves_authority_memory_and_disk_unchanged(tmp_path, monkeypatch):
    root, store, rrm, request = retired(tmp_path)
    before = store._authority_file.read_bytes()
    tombstones = dict(rrm._tombstones)
    replace = os.replace
    def fail(source, destination):
        if Path(destination) == store._authority_file:
            assert not rrm._consumptions
            assert not rrm._capabilities
            raise OSError('injected disk failure')
        return replace(source, destination)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(RuntimeError, match='Durable reregistration failed'):
        rrm.conditional_reregister_resource(request, materialization_descriptor={'display_name': 'B'})
    assert not rrm._consumptions
    assert not rrm._capabilities
    assert rrm._tombstones == tombstones
    assert store._authority_file.read_bytes() == before
    with pytest.raises(RuntimeError, match='poisoned'): rrm.get_capability('c')


def test_r4_durable_success_precedes_memory_publication(tmp_path, monkeypatch):
    root, store, rrm, request = retired(tmp_path)
    commit = store.commit
    observed = []
    def check(expected, candidate):
        assert not rrm._consumptions and not rrm._capabilities
        assert candidate['consumptions'][0]['successor_candidate_proposal_id'] == 'p'
        assert candidate['consumptions'][0]['successor_candidate_decision_id'] == 'd'
        result = commit(expected, candidate)
        assert not rrm._consumptions and not rrm._capabilities
        observed.append(store.load())
        return result
    monkeypatch.setattr(store, 'commit', check)
    descriptor = {'display_name': 'B', 'capability_claims': ['compute']}
    result = rrm.conditional_reregister_resource(request, materialization_descriptor=descriptor)
    assert result.outcome == ConditionalReregistrationOutcome.REREGISTERED
    record = observed[0]
    assert len(record['consumptions']) == len(record['active_governed']) == 1
    assert record['active_governed'][0]['governed_registration_id'] == result.successor_governed_registration_id
    assert rrm.get_capability('c').generation == 2
    descriptor['capability_claims'].append('changed')
    assert record['consumptions'][0]['successor_materialization_descriptor']['capability_claims'] == ['compute']


def test_r5_restart_reuses_successor_and_preserves_consumption(tmp_path, monkeypatch):
    root, store, rrm, request = retired(tmp_path)
    first = rrm.conditional_reregister_resource(request, materialization_descriptor={'display_name': 'B'})
    restarted = RegistryResourceManager(False, store_at(root))
    def no_mint(*args): raise AssertionError('second mint')
    monkeypatch.setattr(restarted, '_generate_governed_registration_id', no_mint)
    result = restarted.conditional_reregister_resource(request, materialization_descriptor={'display_name': 'attacker'})
    assert result.outcome == ConditionalReregistrationOutcome.REREGISTRATION_RECOVERED
    assert result.successor_governed_registration_id == first.successor_governed_registration_id
    assert restarted.get_capability('c').name == 'B'
    assert len(restarted._consumptions) == 1
    again = restarted.conditional_reregister_resource(request)
    assert again.outcome == ConditionalReregistrationOutcome.REREGISTRATION_ALREADY_APPLIED
    wrong = ConditionalReregistrationRequest(ResourceType.CAPABILITY, 'c', 'lineage-A', 1, 'other', 'decision')
    assert restarted.conditional_reregister_resource(wrong).outcome == ConditionalReregistrationOutcome.PENDING_SUCCESSOR_MISMATCH
    result = restarted.conditional_retire_resource(ConditionalRetirementRequest(ResourceType.CAPABILITY, 'c', first.successor_governed_registration_id, 2))
    assert result.outcome == ConditionalRetirementOutcome.RETIRED
    restarted_again = RegistryResourceManager(False, store_at(root))
    assert restarted_again.conditional_reregister_resource(request).outcome == ConditionalReregistrationOutcome.STALE_RETIRED_LINEAGE
    assert restarted_again.get_capability('c') is None


PUBLIC = [name for name, value in RegistryResourceManager.__dict__.items() if not name.startswith('_') and callable(value)]
@pytest.mark.parametrize('method', PUBLIC)
def test_r6_r7_r8_every_public_authority_method_fails_immediately_when_poisoned(method):
    rrm = RegistryResourceManager(False)
    rrm.register_capability(CapabilityResource('c', 'c', governed_registration_id='A'))
    rrm._poison_rrm('injected')
    bound = getattr(rrm, method)
    kwargs = {p.name: None for p in inspect.signature(bound).parameters.values()
              if p.default is inspect.Parameter.empty}
    # None inputs deliberately prove poison is checked before request inspection.
    with pytest.raises(RuntimeError, match='poisoned'):
        bound(**kwargs)


@pytest.mark.parametrize('evidence', ['continuity', 'pkb', 'missions', 'logs', 'ame_memory'])
def test_r9_cold_pre_m32_fails_closed_without_creating_authority(tmp_path, evidence):
    root = tmp_path / 'old'
    file = root / ('continuity/identity.json' if evidence == 'continuity' else evidence + '/existing')
    file.parent.mkdir(parents=True)
    file.write_text('{"installation_id":"existing-install"}')
    before = file.read_bytes()
    with pytest.raises(RuntimeError, match='COLD PRE-M32'):
        RegistryResourceManager(False, store_at(root))
    assert not (root / 'rrm/authority.json').exists()
    assert file.read_bytes() == before
    if evidence != 'continuity': assert not (root / 'continuity/identity.json').exists()


def test_r10_empty_temporary_install_starts_empty(tmp_path):
    store = store_at(tmp_path / 'new')
    rrm = RegistryResourceManager(False, store)
    assert not rrm.list_capabilities()
    assert store.load()['active_governed'] == []
    assert rrm._durable_revision == store.load()['revision'] == 1


def test_r11_live_migration_revision_one_restart_preserves_authority(tmp_path, monkeypatch):
    store = store_at(tmp_path / 'live')
    live = RegistryResourceManager(False)
    live.register_capability(CapabilityResource('c', 'alias', governed_registration_id='live-lineage'))
    live._capabilities['c'].generation = 7
    snap = live._build_durable_state_snapshot()
    state = store.create_from_live_rrm(store.get_continuity_identity(), snap['tombstones'], snap['consumptions'], snap['first_governances'], snap['active_governed'])
    assert state['revision'] == 1
    assert store.commit(0, state)['outcome'] == 'committed'
    restarted = RegistryResourceManager(False, store_at(tmp_path / 'live'))
    assert restarted._durable_revision == 1
    assert restarted._build_durable_state_snapshot()['active_governed'] == state['active_governed']
    def no_mint(*args): raise AssertionError('authority reminted')
    monkeypatch.setattr(restarted, '_generate_governed_registration_id', no_mint)
    restarted.register_capability(CapabilityResource('c', 'alias'))
    resource = restarted.get_capability('c')
    assert (resource.governed_registration_id, resource.generation) == ('live-lineage', 7)
    assert len(restarted._build_durable_state_snapshot()['active_governed']) == 1


def test_r12_revision_mismatch_rejects_bad_candidate_and_stale_writer(tmp_path):
    store = store_at(tmp_path / 'revision')
    initial = store.initialize_fresh()
    assert store.commit(0, initial)['outcome'] == 'committed'
    before = store._authority_file.read_bytes()
    assert store.commit(1, initial)['outcome'] == 'revision_mismatch'
    assert store.commit(0, initial)['outcome'] == 'revision_mismatch'
    assert store._authority_file.read_bytes() == before


def test_post_commit_publication_failure_poisoned_restart_recovers(tmp_path):
    root, store, rrm, request = retired(tmp_path)
    class BrokenPublication(dict):
        def __setitem__(self, key, value): raise RuntimeError('publication failed')
    rrm._capabilities = BrokenPublication()
    with pytest.raises(RuntimeError, match='publication failed'):
        rrm.conditional_reregister_resource(request, materialization_descriptor={'display_name': 'B'})
    with pytest.raises(RuntimeError, match='poisoned'): rrm.list_capabilities()
    restarted = RegistryResourceManager(False, store_at(root))
    result = restarted.conditional_reregister_resource(request)
    assert result.outcome == ConditionalReregistrationOutcome.REREGISTRATION_RECOVERED
    assert restarted.get_capability('c').governed_registration_id == result.successor_governed_registration_id
