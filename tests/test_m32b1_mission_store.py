"""M32B-1 MissionRecord/store foundation tests T1-T30 (+port contract).

T1  fresh create -> revision 1
T2  restart/new store object -> exact durable record load
T3  deterministic mission_definition_digest
T4  duplicate mission create -> fail closed, original unchanged
T5  durable revision mismatch -> fail closed
T6  valid update N -> N+1
T7  durable write failure -> no process-local authority publication/advance
T8  corrupt JSON -> fail closed
T9  unknown/future schema -> fail closed
T10 installation_id mismatch -> fail closed
T11 ALL frozen ActionState values round-trip
T12 RRM values are expectations only (store never consults RRM authority)
T13 no Python executor/service/callback/object identity persisted
T14 no reusable confirmation authority persisted
T15 historical mission without valid M32B record -> NON_RESUMABLE (None)
T16 new mission creation allowed despite unrelated pre-M32B artifacts
T17 real ~/.intent-os untouched (isolated paths only)
T18 atomic replacement failure before replace preserves prior durable record
T19 deep detachment / no nested aliasing
T20 unambiguous schema/revision representation
T21 path traversal mission_id rejected
T22 immutable identity change on update rejected
T23 mission definition digest replacement rejected
T24 missing required field rejected
T25 invalid enum rejected
T26 invalid revision <= 0 rejected
T27 load returns detached independent object
T28 create failure leaves no partial canonical file
T29 update on nonexistent mission fails
T30 sequential stale writer detection (NOT simultaneous multiprocess CAS)

All paths isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from intent_kernel.mission.mission_record import (
    ActionPlanEntry,
    ActionState,
    CompletionState,
    CompletionStateRecord,
    DurableActionState,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
    VerificationState,
    VerificationStateRecord,
)
from intent_kernel.mission.store import (
    MissionRecordStorePort,
    MissionRecordValidationError,
)
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore


def _store(tmp_path: Path, name: str = "t") -> JsonFileMissionRecordStore:
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _authority_file(store: JsonFileMissionRecordStore, mission_id: str) -> Path:
    return store._missions_dir / f"{mission_id}.json"  # noqa: SLF001


def _definition(objective: str = "objective") -> MissionDefinition:
    return MissionDefinition(
        objective=objective,
        context={"k": "v", "n": 1},
        success_criteria=("s1",),
        scope=("a",),
    )


def _digest(defn: MissionDefinition) -> str:
    probe = MissionRecord(
        mission_id="probe", installation_id="probe-install",
        mission_definition=defn,
    )
    return probe.compute_definition_digest()


def _plan() -> tuple:
    return ({
        "action_id": "a1",
        "capability": "cap.one",
        "node_id": "n1",
        "dependencies": [],
        "request_semantics_digest": "d1",
    },)


def _record(
    store: JsonFileMissionRecordStore,
    mission_id: str = "m1",
    revision: int = 1,
    status: MissionStatus = MissionStatus.CREATED,
    definition: MissionDefinition | None = None,
    digest: str | None = None,
    plan=None,
    action_states=None,
    runtime_id: str = "rt-1",
) -> MissionRecord:
    ident = store.get_continuity_identity()
    definition = definition if definition is not None else _definition()
    if digest is None:
        digest = _digest(definition)
    return MissionRecord(
        mission_id=mission_id,
        installation_id=ident,
        revision=revision,
        runtime_id=runtime_id,
        mission_definition=definition,
        mission_definition_digest=digest,
        mission_status=status,
        plan=_plan() if plan is None else plan,
        action_states={} if action_states is None else action_states,
    )


def test_t1_fresh_create_revision_one(tmp_path):
    store = _store(tmp_path)
    result = store.create(_record(store))
    assert result.outcome == "committed"
    assert result.revision == 1
    assert _authority_file(store, "m1").is_file()
    loaded = store.load("m1")
    assert loaded["revision"] == 1
    assert loaded["mission_id"] == "m1"


def test_t2_new_store_object_exact_load(tmp_path):
    store = _store(tmp_path)
    record = _record(
        store, mission_id="m2",
        action_states={"a1": DurableActionState(
            action_id="a1", node_id="n1", state=ActionState.AUTHORIZED,
            expected_resource_id="r", expected_governed_registration_id="g",
            expected_resource_generation=2)},
    )
    assert store.create(record).outcome == "committed"

    store2 = JsonFileMissionRecordStore(
        missions_dir=store._missions_dir,  # noqa: SLF001
        continuity_file=store._continuity_file,  # noqa: SLF001
    )
    assert store2.load("m2") == store.load("m2")


def test_t3_deterministic_digest(tmp_path):
    store = _store(tmp_path)
    d1, d2 = _definition("same"), _definition("same")
    assert _digest(d1) == _digest(d2)
    assert _digest(_definition("same")) != _digest(_definition("changed"))
    # No timestamps/object ids: same semantics at different times -> same digest.
    r1 = _record(store, mission_id="t3a")
    r2 = _record(store, mission_id="t3b")
    assert r1.mission_definition_digest == r2.mission_definition_digest
    assert len(r1.mission_definition_digest) == 64


def test_t4_duplicate_create_fails_closed(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    before = _authority_file(store, "m1").read_bytes()
    result = store.create(_record(store))
    assert result.outcome == "already_exists"
    assert _authority_file(store, "m1").read_bytes() == before
    assert store.load("m1")["revision"] == 1


def test_t5_durable_revision_mismatch_fails_closed(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    import dataclasses
    current = MissionRecord.from_dict(store.load("m1"))
    advanced = dataclasses.replace(current, revision=2, mission_status=MissionStatus.RUNNING)
    assert store.commit(1, advanced).outcome == "committed"  # disk now rev 2
    stale = dataclasses.replace(current, revision=2, mission_status=MissionStatus.PAUSED)
    result = store.commit(1, stale)
    assert result.outcome == "revision_mismatch"
    assert store.load("m1")["revision"] == 2
    assert store.load("m1")["mission_status"] == "RUNNING"


def test_t6_valid_update_n_to_n_plus_1(tmp_path):
    # M32B-2 contract: the action set is frozen by the frozen plan, so the
    # updated action must exist (PENDING) at creation; the update evolves
    # only its state.
    store = _store(tmp_path)
    assert store.create(_record(
        store,
        plan=({"action_id": "a1", "capability": "c", "node_id": "n1",
               "dependencies": [], "request_semantics_digest": "d"},),
        action_states={"a1": DurableActionState(
            action_id="a1", node_id="n1", state=ActionState.PENDING)},
    )).outcome == "committed"
    import dataclasses
    current = MissionRecord.from_dict(store.load("m1"))
    states = dict(current.action_states)
    states["a1"] = DurableActionState(
        action_id="a1", node_id="n1", state=ActionState.DISPATCHING)
    updated = dataclasses.replace(current, revision=2, action_states=states)
    result = store.commit(1, updated)
    assert result.outcome == "committed"
    assert result.revision == 2
    loaded = store.load("m1")
    assert loaded["revision"] == 2
    assert loaded["action_states"]["a1"]["state"] == "DISPATCHING"


def test_t7_write_failure_no_publication(tmp_path, monkeypatch):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    before = store.load("m1")

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", _boom)
    import dataclasses
    current = MissionRecord.from_dict(before)
    result = store.commit(1, dataclasses.replace(current, revision=2))
    assert result.outcome == "io_error"
    # No process-local advance: durable authority still revision 1.
    assert store.load("m1") == before


def test_t8_corrupt_json_fails_closed(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    _authority_file(store, "m1").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")


def test_t9_unknown_schema_fails_closed(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    data = json.loads(_authority_file(store, "m1").read_text(encoding="utf-8"))
    data["schema_version"] = 999
    _authority_file(store, "m1").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")


def test_t10_installation_mismatch_fails_closed(tmp_path):
    store = _store(tmp_path, "a")
    assert store.create(_record(store, mission_id="mx")).outcome == "committed"
    store_b = JsonFileMissionRecordStore(
        missions_dir=store._missions_dir,  # noqa: SLF001 - shared missions dir
        continuity_file=tmp_path / "b" / "cont" / "identity.json",
    )
    (tmp_path / "b" / "cont").mkdir(parents=True, exist_ok=True)
    with pytest.raises(MissionRecordValidationError):
        store_b.load("mx")


def test_t11_all_action_states_round_trip(tmp_path):
    store = _store(tmp_path)
    states = {s.name: DurableActionState(action_id="a", node_id="n", state=s)
              for s in ActionState}
    assert len(states) == 11
    record = _record(store, mission_id="m11", action_states=states)
    assert store.create(record).outcome == "committed"
    loaded = store.load("m11")["action_states"]
    for name, state in states.items():
        assert loaded[name]["state"] == state.state.value


def test_t12_rrm_values_are_expectations_only(tmp_path):
    store = _store(tmp_path)
    # Expected values match NO real RRM authority; the store never consults RRM.
    states = {"a1": DurableActionState(
        action_id="a1", node_id="n1", state=ActionState.AUTHORIZED,
        expected_resource_id="no-such-resource",
        expected_governed_registration_id="gov-nonexistent",
        expected_resource_generation=4242,
        expected_executor_kind="core_app",
        expected_executor_logical_id="no-such-app")}
    record = _record(store, mission_id="m12", action_states=states)
    assert store.create(record).outcome == "committed"
    loaded = store.load("m12")["action_states"]["a1"]
    assert loaded["expected_governed_registration_id"] == "gov-nonexistent"
    assert loaded["expected_resource_generation"] == 4242
    # MissionRecord carries no current-authority RRM fields.
    top = store.load("m12")
    for forbidden in ("governed_registration_id", "current_generation",
                      "resource_status", "tombstone", "consumption",
                      "first_governance"):
        assert forbidden not in top


def test_t13_no_python_identity_persisted(tmp_path):
    store = _store(tmp_path)
    states = {"a1": DurableActionState(
        action_id="a1", node_id="n1", state=ActionState.RESULT_RECORDED,
        result={"ok": True, "nested": [1, 2, {"x": "y"}]})}
    record = _record(store, mission_id="m13", action_states=states)
    assert store.create(record).outcome == "committed"
    raw = _authority_file(store, "m13").read_text(encoding="utf-8")
    assert "object at 0x" not in raw
    assert store.load("m13")["action_states"]["a1"]["result"] == {
        "ok": True, "nested": [1, 2, {"x": "y"}]}
    # Non-serializable Python objects fail closed at construction.
    with pytest.raises(ValueError):
        DurableActionState(action_id="a", node_id="n",
                           state=ActionState.RESULT_RECORDED, result=object())
    import threading
    with pytest.raises(ValueError):
        MissionRecord(
            mission_id="bad", installation_id="i",
            action_states={"a": DurableActionState(
                action_id="a", node_id="n", result=threading.Lock())},
        )


def test_t14_no_reusable_confirmation_authority(tmp_path):
    store = _store(tmp_path)
    record = _record(store, mission_id="m14", action_states={
        "a1": DurableActionState(action_id="a1", node_id="n1",
                                 state=ActionState.RECONFIRMATION_REQUIRED)})
    assert store.create(record).outcome == "committed"
    top = store.load("m14")
    blob = json.dumps(top)
    for forbidden in ("confirmation_token", "session_authorization",
                      "CONFIRMED", "approved", "session_id"):
        assert forbidden not in top
        assert forbidden not in blob
    assert ActionState.RECONFIRMATION_REQUIRED.value == "RECONFIRMATION_REQUIRED"


def test_t15_missing_record_non_resumable(tmp_path):
    store = _store(tmp_path)
    assert store.load("never-created") is None
    assert store.exists("never-created") is False


def test_t16_new_mission_allowed_despite_artifacts(tmp_path):
    store = _store(tmp_path)
    missions = store._missions_dir  # noqa: SLF001
    (missions / "legacy.json").write_text("{broken", encoding="utf-8")
    (missions / "notes.txt").write_text("historical notes", encoding="utf-8")
    assert store.create(_record(store, mission_id="fresh")).outcome == "committed"
    assert store.load("fresh")["revision"] == 1


def test_t17_paths_isolated(tmp_path):
    store = _store(tmp_path)
    assert tmp_path in store._missions_dir.parents  # noqa: SLF001
    assert tmp_path in store._continuity_file.parents  # noqa: SLF001
    assert ".intent-os" not in str(store._missions_dir)
    home = Path.home()
    assert store._missions_dir != home / ".intent-os" / "missions"


def test_t18_prereplace_failure_preserves_prior(tmp_path, monkeypatch):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    before = _authority_file(store, "m1").read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("simulated temp failure")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _boom)
    import dataclasses
    current = MissionRecord.from_dict(store.load("m1"))
    result = store.commit(1, dataclasses.replace(current, revision=2))
    assert result.outcome == "io_error"
    assert _authority_file(store, "m1").read_bytes() == before


def test_t19_deep_detachment(tmp_path):
    store = _store(tmp_path)
    caller_plan = [{
        "action_id": "a1", "capability": "c", "node_id": "n",
        "dependencies": [], "request_semantics_digest": "d",
        "nested": {"k": [1, 2]},
    }]
    record = _record(store, mission_id="m19", plan=caller_plan)
    caller_plan[0]["nested"]["k"].append(999)
    caller_plan.append({"action_id": "evil"})
    assert len(record.plan) == 1
    assert record.plan[0]["nested"] == {"k": [1, 2]}
    assert store.create(record).outcome == "committed"

    serialized = record.to_dict()
    serialized["plan"][0]["nested"]["k"].append(1000)
    assert store.load("m19")["plan"][0]["nested"] == {"k": [1, 2]}


def test_t20_single_revision_single_schema_authority(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    data = store.load("m1")
    assert list(data.keys()).count("revision") == 1
    assert "envelope" not in data
    assert "schema" not in [k for k in data.keys() if k != "schema_version"]
    assert data["schema_version"] == 1


def test_t21_path_traversal_rejected(tmp_path):
    store = _store(tmp_path)
    bad_ids = ["../x", "a/b", "..\\x", "/abs", "C:\\w", "C:m", "a:b", "", "   ",
               " ok "]
    for bad in bad_ids:
        with pytest.raises(MissionRecordValidationError):
            store.load(bad if bad else " ")
        with pytest.raises(MissionRecordValidationError):
            store.exists(bad if bad else " ")
    with pytest.raises(MissionRecordValidationError):
        store.create(_record(store, mission_id="../evil"))
    with pytest.raises(MissionRecordValidationError):
        store.commit(0, _record(store, mission_id="a/b"))


def test_t22_immutable_identity_change_rejected(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    import dataclasses
    current = MissionRecord.from_dict(store.load("m1"))
    for field, value in (("runtime_id", "rt-other"),
                         ("installation_id", "install-other"),
                         ("created_at", "2000-01-01T00:00:00+00:00")):
        candidate = dataclasses.replace(current, revision=2, **{field: value})
        with pytest.raises(MissionRecordValidationError):
            store.commit(1, candidate)
    # mission_id change addresses a different file -> not_found, still closed.
    moved = dataclasses.replace(current, revision=2, mission_id="other")
    result = store.commit(1, moved)
    assert result.outcome == "not_found"
    assert store.load("m1")["revision"] == 1


def test_t23_digest_replacement_rejected(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    import dataclasses
    current = MissionRecord.from_dict(store.load("m1"))
    # New definition but stale digest field -> immutable identity mismatch.
    new_def = _definition("changed-objective")
    candidate = dataclasses.replace(
        current, revision=2, mission_definition=new_def)
    with pytest.raises(MissionRecordValidationError):
        store.commit(1, candidate)
    # Same definition but tampered digest characters -> digest check fails.
    tampered = dataclasses.replace(
        current, revision=2,
        mission_definition_digest="0" * 64)
    with pytest.raises(MissionRecordValidationError):
        store.commit(1, tampered)
    assert store.load("m1")["revision"] == 1


def test_t24_missing_required_field_rejected(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    data = json.loads(_authority_file(store, "m1").read_text(encoding="utf-8"))
    del data["plan"]
    _authority_file(store, "m1").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")


def test_t25_invalid_enum_rejected(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    data = json.loads(_authority_file(store, "m1").read_text(encoding="utf-8"))
    data["action_states"] = {"a1": {"action_id": "a1", "node_id": "n1",
                                    "state": "BOGUS"}}
    _authority_file(store, "m1").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")
    data["action_states"] = {}
    data["mission_status"] = "BOGUS"
    _authority_file(store, "m1").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")


def test_t26_invalid_revision_rejected(tmp_path):
    with pytest.raises(ValueError):
        MissionRecord(mission_id="m", installation_id="i", revision=0)
    with pytest.raises(ValueError):
        MissionRecord(mission_id="m", installation_id="i", revision=-3)
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    data = json.loads(_authority_file(store, "m1").read_text(encoding="utf-8"))
    data["revision"] = 0
    _authority_file(store, "m1").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m1")


def test_t27_load_returns_independent_object(tmp_path):
    store = _store(tmp_path)
    assert store.create(_record(store)).outcome == "committed"
    first = store.load("m1")
    second = store.load("m1")
    assert first == second
    assert first is not second
    first["plan"].append({"action_id": "evil"})
    first["action_states"]["x"] = {}
    assert second == store.load("m1")


def test_t28_create_failure_no_partial_file(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def _boom(*args, **kwargs):
        raise OSError("simulated create failure")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _boom)
    result = store.create(_record(store, mission_id="partial"))
    assert result.outcome == "io_error"
    assert not _authority_file(store, "partial").exists()
    assert store.exists("partial") is False


def test_t29_update_nonexistent_fails(tmp_path):
    store = _store(tmp_path)
    record = _record(store, mission_id="ghost", revision=1)
    # create() would succeed; commit() without durable file must not.
    result = store.commit(0, record)
    assert result.outcome == "not_found"
    assert not _authority_file(store, "ghost").exists()


def test_t30_sequential_stale_writer_detected(tmp_path):
    # Two store objects, same files. Proves sequential stale-writer
    # detection. NOT simultaneous multiprocess CAS (unsupported by contract).
    store_a = _store(tmp_path, "shared")
    store_b = JsonFileMissionRecordStore(
        missions_dir=store_a._missions_dir,  # noqa: SLF001
        continuity_file=store_a._continuity_file,  # noqa: SLF001
    )
    assert store_a.create(_record(store_a, mission_id="s")).outcome == "committed"
    import dataclasses
    fresh_b = MissionRecord.from_dict(store_b.load("s"))
    assert store_b.commit(
        1, dataclasses.replace(fresh_b, revision=2,
                               mission_status=MissionStatus.RUNNING)
    ).outcome == "committed"
    stale_a = MissionRecord.from_dict(store_a.load("s"))
    assert stale_a.revision == 2  # A sees current durable truth on reload...
    # ...but a writer holding the OLD expectation still fails closed:
    held_old = dataclasses.replace(
        MissionRecord.from_dict(store_a.load("s")),
        revision=2, mission_status=MissionStatus.PAUSED)
    # craft the stale expectation explicitly: disk is 2, writer expects 1
    result = store_a.commit(1, held_old)
    assert result.outcome == "revision_mismatch"
    assert store_a.load("s")["mission_status"] == "RUNNING"


def test_port_contract_aligned():
    assert issubclass(JsonFileMissionRecordStore, MissionRecordStorePort)
    import inspect
    for name in ("create", "load", "commit", "exists"):
        port_fn = getattr(MissionRecordStorePort, name)
        impl_fn = getattr(JsonFileMissionRecordStore, name)
        assert not inspect.iscoroutinefunction(
            port_fn), f"port.{name} must be sync"
        assert not inspect.iscoroutinefunction(
            impl_fn), f"impl.{name} must be sync"
