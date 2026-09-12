"""M32B-1 targeted repair — ProductBridge storage-path passthrough + build invariants.

Scope (per correction brief, read-only production semantics preserved):
- T-PB1: explicit authority/continuity paths reach the canonical RRM durable store.
- T-PB2: omitted paths preserve production defaults (under patched Path.home).
- T-PB3: single-build invariant — exactly 1 KernelBuilder.build + 1 bootstrap_govern.
- T-FRESH: fresh isolated single build governs finance.intent exactly once.
- T-SECOND: same-store second build diagnostic — records outcome, never fails
  the suite (restart semantics are OUT OF SCOPE for repair in this movement).

All paths are isolated under tmp_path; real user state is never touched
(tests/conftest.py audit hook enforces this independently).
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.promotion.promotion_service import (
    BootstrapGovernanceError,
    CanonicalResourcePromotionService,
)
from product_bridge import ProductBridge


def _isolated_paths(store_root: Path):
    return (
        store_root / "rrm" / "authority.json",
        store_root / "continuity" / "identity.json",
    )


def test_pb1_explicit_paths_reach_canonical_rrm(tmp_path, m32a_isolated_store_root):
    authority_file, continuity_file = _isolated_paths(m32a_isolated_store_root)
    assert not authority_file.exists()
    assert not continuity_file.exists()

    bridge = ProductBridge(
        data_root=tmp_path,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )

    # Evidence must come from the actual canonical RRM durable store,
    # not from constructor attribute assignment.
    store = bridge.components.resource_manager._durable_store
    assert store is not None
    assert Path(store._authority_file) == authority_file
    assert Path(store._continuity_file) == continuity_file
    assert authority_file.is_file()
    assert tmp_path in authority_file.parents


def test_pb2_omitted_paths_preserve_production_defaults(tmp_path):
    bridge = ProductBridge(data_root=tmp_path)

    store = bridge.components.resource_manager._durable_store
    assert store is not None
    expected_authority = Path.home() / ".intent-os" / "rrm" / "authority.json"
    expected_continuity = Path.home() / ".intent-os" / "continuity" / "identity.json"
    assert Path(store._authority_file) == expected_authority
    assert Path(store._continuity_file) == expected_continuity


def test_pb3_single_build_invariant(tmp_path, m32a_isolated_store_root):
    authority_file, continuity_file = _isolated_paths(m32a_isolated_store_root)
    real_build = KernelBuilder.build
    real_bootstrap = CanonicalResourcePromotionService.bootstrap_govern
    build_count = 0
    bootstrap_count = 0

    def counting_build(self, *args, **kwargs):
        nonlocal build_count
        build_count += 1
        return real_build(self, *args, **kwargs)

    def counting_bootstrap(self, *args, **kwargs):
        nonlocal bootstrap_count
        bootstrap_count += 1
        return real_bootstrap(self, *args, **kwargs)

    with mock.patch.object(KernelBuilder, "build", counting_build):
        with mock.patch.object(
            CanonicalResourcePromotionService, "bootstrap_govern", counting_bootstrap
        ):
            ProductBridge(
                data_root=tmp_path,
                authority_file=authority_file,
                continuity_file=continuity_file,
            )

    assert build_count == 1
    assert bootstrap_count == 1


def test_fresh_single_build_governs_finance_exactly_once(
    tmp_path, m32a_isolated_store_root
):
    authority_file, continuity_file = _isolated_paths(m32a_isolated_store_root)
    assert not authority_file.exists()

    bridge = ProductBridge(
        data_root=tmp_path,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )

    snapshot = bridge.components.resource_manager.get_capability("finance.intent")
    assert snapshot is not None
    assert snapshot.governed_registration_id != ""
    assert snapshot.generation == 2
    assert authority_file.is_file()
    assert tmp_path in authority_file.parents

    print(
        f"FRESH_FINANCE_GRID={snapshot.governed_registration_id} "
        f"FRESH_FINANCE_GENERATION={snapshot.generation}"
    )


def test_same_store_second_build_diagnostic(tmp_path):
    """Diagnostic only: two fresh bridges sharing one durable store.

    Production bootstrap semantics are NOT modified to make this pass.
    Either outcome is recorded; the test itself only fails on an
    unexpected exception type.
    """
    store_root = tmp_path / ".intent-os"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    authority_file, continuity_file = _isolated_paths(store_root)

    data1 = tmp_path / "data1"
    data1.mkdir()
    ProductBridge(
        data_root=data1,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )
    assert authority_file.is_file()

    data2 = tmp_path / "data2"
    data2.mkdir()
    try:
        ProductBridge(
            data_root=data2,
            authority_file=authority_file,
            continuity_file=continuity_file,
        )
        result = "SUCCESS"
    except BootstrapGovernanceError as exc:
        assert "already_governed" in str(exc)
        result = "FAIL_CLOSED_ALREADY_GOVERNED"

    print(f"SECOND_BUILD_RESULT={result}")
