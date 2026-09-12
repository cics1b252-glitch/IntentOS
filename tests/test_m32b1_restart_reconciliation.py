"""M32B-1 restart bootstrap reconciliation — required tests T1-T12.

Covers the proven root cause: bootstrap_govern rejected every non-empty
governed_registration_id as already_governed, including resources correctly
reconciled from M32A durable authority after restart.

T1  fresh first build governs once (grid non-empty, gen 2, exactly one fact)
T2  second PROCESS, same store: succeeds, same GRID/gen, no mint, revision stable
T3  third restart: succeeds, same GRID/gen/fact, no revision increase
T4  tombstoned built-in is never resurrected (fails closed)
T5  durable lineage mismatch (fact vs active) fails closed
T6  missing fact / corrupt authority file fail closed
T7  unexplained pre-governed live resource still fails; same-process duplicate
    bootstrap is NOT accepted
T8  no new lineage consumption from reconciliation
T9  no generation advance from restart
T10 fresh executor objects; no Python object identity persisted; exact-object
    binding holds in the new process objects
T11 all 12 built-ins reconcile (8 capabilities + 3 agents + 1 provider)
T12 authority revision stability across reconciliation

All paths isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from intent_kernel.application.composition import (
    KernelBuilder,
    _build_bootstrap_declarations,
)
from intent_kernel.promotion.promotion_service import BootstrapGovernanceError
from intent_kernel.rrm.models import (
    ConditionalRetirementOutcome,
    ConditionalRetirementRequest,
    ResourceType,
)
from intent_kernel.rrm.service import RegistryResourceManager
from product_bridge import ProductBridge

REPO_ROOT = Path(__file__).resolve().parent.parent

BUILTIN_IDS: tuple[tuple[str, str], ...] = (
    tuple(("capability", c) for c in (
        "finance.intent",
        "knowledge.intent",
        "knowledge.project.create",
        "knowledge.project.list",
        "knowledge.search",
        "engineering.intent",
        "engineering.project.create",
        "engineering.project.list",
    ))
    + tuple(("agent", a) for a in ("finance", "knowledge", "engineering"))
    + (("provider", "mock"),)
)

_CHILD_CODE = """
import sys, json
from pathlib import Path
store_root, data_root, ids_json = sys.argv[1], sys.argv[2], sys.argv[3]
from product_bridge import ProductBridge
sr = Path(store_root)
try:
    b = ProductBridge(
        data_root=Path(data_root),
        authority_file=sr / "rrm" / "authority.json",
        continuity_file=sr / "continuity" / "identity.json",
    )
    rrm = b.components.resource_manager
    out = {"result": "SUCCESS"}
    for kind, rid in json.loads(ids_json):
        if kind == "capability":
            s = rrm.get_capability(rid)
        elif kind == "agent":
            s = rrm.get_agent(rid)
        else:
            s = rrm.get_provider(rid)
        out[rid] = [s.governed_registration_id, s.generation, str(s.status)]
    print("AUDIT_JSON:" + json.dumps(out))
except Exception as e:
    print("AUDIT_JSON:" + json.dumps({"result": "FAIL", "exc": type(e).__name__, "msg": str(e)}))
"""


def _fresh_process_build(
    store_root: Path, data_root: Path
) -> dict:
    """Build a canonical bridge in a FRESH OS process (true restart)."""
    data_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_CODE, str(store_root), str(data_root),
         json.dumps([list(p) for p in BUILTIN_IDS])],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO_ROOT),
        env=env,
    )
    payload = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("AUDIT_JSON:"):
            payload = json.loads(line[len("AUDIT_JSON:"):])
    assert payload is not None, (
        f"child produced no AUDIT_JSON: rc={proc.returncode} "
        f"stdout={proc.stdout[-2000:]} stderr={proc.stderr[-2000:]}"
    )
    return payload


def _store_paths(store_root: Path):
    return (
        store_root / "rrm" / "authority.json",
        store_root / "continuity" / "identity.json",
    )


def _read_authority(authority_file: Path) -> dict:
    return json.loads(authority_file.read_text(encoding="utf-8"))


def _build_bridge(data_root: Path, authority_file: Path, continuity_file: Path):
    data_root.mkdir(parents=True, exist_ok=True)
    return ProductBridge(
        data_root=data_root,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )


def _snapshot12(rrm) -> dict:
    out = {}
    for kind, rid in BUILTIN_IDS:
        if kind == "capability":
            s = rrm.get_capability(rid)
        elif kind == "agent":
            s = rrm.get_agent(rid)
        else:
            s = rrm.get_provider(rid)
        assert s is not None, f"missing snapshot for {kind}:{rid}"
        out[rid] = (s.governed_registration_id, s.generation, str(s.status))
    return out


def _isolated_store(tmp_path: Path, name: str = ".intent-os") -> Path:
    store_root = tmp_path / name
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return store_root


def test_t1_fresh_first_build_governs_once(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)
    assert not authority_file.exists()

    bridge = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    snap = bridge.components.resource_manager.get_capability("finance.intent")
    assert snap.governed_registration_id != ""
    assert snap.generation == 2

    data = _read_authority(authority_file)
    facts = [f for f in data["first_governances"]
             if f["resource_kind"] == "capability" and f["resource_id"] == "finance.intent"]
    assert len(facts) == 1
    assert facts[0]["governed_registration_id"] == snap.governed_registration_id
    assert facts[0]["resulting_generation"] == 2


def test_t2_second_process_same_store_reconciles(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    grids1 = _snapshot12(bridge1.components.resource_manager)
    before = _read_authority(authority_file)
    revision1 = before["revision"]
    facts1 = len(before["first_governances"])
    assert facts1 == 12

    payload = _fresh_process_build(store_root, tmp_path / "data2")
    assert payload["result"] == "SUCCESS", payload
    for rid, (grid, gen, _status) in grids1.items():
        assert payload[rid][0] == grid, rid
        assert payload[rid][1] == gen, rid

    after = _read_authority(authority_file)
    assert after["revision"] == revision1
    assert len(after["first_governances"]) == facts1
    assert after["consumptions"] == []


def test_t3_third_restart_stable(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    grids1 = _snapshot12(bridge1.components.resource_manager)
    revision1 = _read_authority(authority_file)["revision"]

    payload2 = _fresh_process_build(store_root, tmp_path / "data2")
    assert payload2["result"] == "SUCCESS", payload2
    payload3 = _fresh_process_build(store_root, tmp_path / "data3")
    assert payload3["result"] == "SUCCESS", payload3
    for rid, (grid, gen, _status) in grids1.items():
        assert payload2[rid][:2] == [grid, gen], rid
        assert payload3[rid][:2] == [grid, gen], rid

    data = _read_authority(authority_file)
    assert data["revision"] == revision1
    fg = [f for f in data["first_governances"]
          if f["resource_id"] == "finance.intent"]
    assert len(fg) == 1
    assert fg[0]["governed_registration_id"] == grids1["finance.intent"][0]


def test_t4_tombstoned_builtin_never_resurrected(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    rrm1 = bridge1.components.resource_manager
    snap = rrm1.get_capability("finance.intent")
    retire = rrm1.conditional_retire_resource(
        ConditionalRetirementRequest(
            ResourceType.CAPABILITY, "finance.intent",
            snap.governed_registration_id, snap.generation,
        )
    )
    assert retire.outcome == ConditionalRetirementOutcome.RETIRED, retire.reason

    with pytest.raises(BootstrapGovernanceError) as excinfo:
        _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    assert "finance.intent" in str(excinfo.value)
    assert "resource_not_found" in str(excinfo.value)

    # No resurrection via a plain durable load either.
    from intent_kernel.rrm.persistence import create_json_file_rrm_state_store
    store = create_json_file_rrm_state_store(
        authority_file=str(authority_file), continuity_file=str(continuity_file)
    )
    reloaded = RegistryResourceManager(populate_defaults=False, durable_store=store)
    assert reloaded.get_capability("finance.intent") is None


def test_t5_durable_lineage_mismatch_fails_closed(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    data = _read_authority(authority_file)
    for fg in data["first_governances"]:
        if fg["resource_id"] == "finance.intent":
            fg["governed_registration_id"] = "gov-capability-tampered-0000"
    authority_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BootstrapGovernanceError) as excinfo:
        _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    assert "already_governed" in str(excinfo.value)


def test_t6_missing_fact_fails_closed(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    data = _read_authority(authority_file)
    data["first_governances"] = [
        f for f in data["first_governances"] if f["resource_id"] != "finance.intent"
    ]
    authority_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BootstrapGovernanceError) as excinfo:
        _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    assert "already_governed" in str(excinfo.value)


def test_t6b_corrupt_authority_fails_closed(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    authority_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        _build_bridge(tmp_path / "data2", authority_file, continuity_file)


def test_t7_same_process_duplicate_bootstrap_still_fails(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    revision1 = _read_authority(authority_file)["revision"]

    declarations = _build_bootstrap_declarations(
        bridge.components.capability_registry
    )
    report2 = bridge.components.resource_promotion_service.bootstrap_govern(
        declarations
    )
    assert not report2.success
    reasons = {e.resource_id: e.reason for e in report2.entries if not e.success}
    assert reasons["finance.intent"] == "already_governed"

    # The refused duplicate minted nothing.
    assert _read_authority(authority_file)["revision"] == revision1


def test_t8_no_new_lineage_consumption_on_restart(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    _build_bridge(tmp_path / "data2", authority_file, continuity_file)

    assert _read_authority(authority_file)["consumptions"] == []


def test_t9_no_generation_advance_on_restart(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    grids1 = _snapshot12(bridge1.components.resource_manager)
    bridge2 = _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    grids2 = _snapshot12(bridge2.components.resource_manager)

    assert grids2 == grids1
    for rid, (grid, gen, _status) in grids2.items():
        assert gen == 2, rid


def test_t10_fresh_executor_objects_no_persisted_identity(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    bridge2 = _build_bridge(tmp_path / "data2", authority_file, continuity_file)

    assert bridge1.components.resource_manager is not bridge2.components.resource_manager
    # Exact-object binding holds against the CURRENT-process RRM.
    assert bridge2.ecc.registry.rrm_service is bridge2.components.resource_manager

    raw = authority_file.read_text(encoding="utf-8")
    assert "object at 0x" not in raw
    data = json.loads(raw)

    def _assert_json_scalars(node):
        assert isinstance(node, (dict, list, str, int, float, bool)) or node is None
        if isinstance(node, dict):
            for k, v in node.items():
                assert isinstance(k, str)
                _assert_json_scalars(v)
        elif isinstance(node, list):
            for v in node:
                _assert_json_scalars(v)

    _assert_json_scalars(data)
    for ag in data["active_governed"]:
        assert ag["governed_registration_id"].startswith("gov-")


def test_t11_all_twelve_builtins_reconcile(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    bridge1 = _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    grids1 = _snapshot12(bridge1.components.resource_manager)
    assert len(grids1) == 12

    bridge2 = _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    grids2 = _snapshot12(bridge2.components.resource_manager)

    assert grids2 == grids1
    for rid, (grid, _gen, _status) in grids2.items():
        assert grid != "", rid


def test_t12_authority_revision_stable_on_reconciliation(tmp_path):
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    revision1 = _read_authority(authority_file)["revision"]
    _build_bridge(tmp_path / "data2", authority_file, continuity_file)
    revision2 = _read_authority(authority_file)["revision"]
    _build_bridge(tmp_path / "data3", authority_file, continuity_file)
    revision3 = _read_authority(authority_file)["revision"]

    assert revision2 == revision1
    assert revision3 == revision1


def test_restart_entries_do_not_claim_new_governance(tmp_path):
    """Restart reconciliation reports 'restart_reconciled', never a new mint."""
    store_root = _isolated_store(tmp_path)
    authority_file, continuity_file = _store_paths(store_root)

    _build_bridge(tmp_path / "data1", authority_file, continuity_file)
    components = KernelBuilder().build(
        authority_file=authority_file, continuity_file=continuity_file
    )
    report = components.resource_promotion_service.bootstrap_govern(
        _build_bootstrap_declarations(components.capability_registry)
    )
    # Same-process re-run after a restart-loaded build: durable-loaded facts
    # explain every declaration, so this succeeds WITHOUT any new mint.
    assert report.success
    for entry in report.entries:
        assert entry.success
        assert entry.outcome == "restart_reconciled"
        assert entry.governed_registration_id != ""
    assert "first_governance_applied" not in [e.outcome for e in report.entries]
