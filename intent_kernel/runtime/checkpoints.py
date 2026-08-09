"""Mission Checkpoint Repository Port & Persistence Adapter — RFC-0015 (STUDIO 10.2).

Provides checkpoint saving, loading, listing, and deletion ports backed by
PersistenceEngine or local memory to support mission restart and pause/resume.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from intent_kernel.persistence import MemoryPersistenceEngine, PersistenceEngine
from intent_kernel.runtime.models import MissionCheckpoint


class MissionCheckpointRepositoryPort(ABC):
    """Abstract port interface for checkpoint persistence."""

    @abstractmethod
    async def save_checkpoint(self, checkpoint: MissionCheckpoint) -> bool:
        """Save a mission checkpoint."""
        pass

    @abstractmethod
    async def get_latest_checkpoint(self, runtime_id: str) -> Optional[MissionCheckpoint]:
        """Retrieve the latest checkpoint for a given runtime_id."""
        pass

    @abstractmethod
    async def list_checkpoints(self, runtime_id: str) -> List[MissionCheckpoint]:
        """List all historical checkpoints for a given runtime_id."""
        pass

    @abstractmethod
    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint by ID."""
        pass


class InMemoryCheckpointRepository(MissionCheckpointRepositoryPort):
    """Concrete checkpoint repository adapter backed by Kernel PersistenceEngine abstraction."""

    def __init__(self, persistence_engine: Optional[PersistenceEngine] = None) -> None:
        self._engine = persistence_engine or MemoryPersistenceEngine()
        self._cache: Dict[str, MissionCheckpoint] = {}

    async def save_checkpoint(self, checkpoint: MissionCheckpoint) -> bool:
        key = f"checkpoint:{checkpoint.checkpoint_id}"
        runtime_index_key = f"runtime_checkpoints:{checkpoint.runtime_id}"

        self._cache[checkpoint.checkpoint_id] = checkpoint
        await self._engine.write(key, checkpoint.to_dict())

        # Update index
        existing_index = await self._engine.read(runtime_index_key) or []
        if checkpoint.checkpoint_id not in existing_index:
            existing_index.append(checkpoint.checkpoint_id)
            await self._engine.write(runtime_index_key, existing_index)

        return True

    async def get_latest_checkpoint(self, runtime_id: str) -> Optional[MissionCheckpoint]:
        runtime_index_key = f"runtime_checkpoints:{runtime_id}"
        index = await self._engine.read(runtime_index_key) or []

        if not index:
            return None

        latest_id = index[-1]
        if latest_id in self._cache:
            return self._cache[latest_id]

        data = await self._engine.read(f"checkpoint:{latest_id}")
        if not data:
            return None

        chk = MissionCheckpoint(
            checkpoint_id=data.get("checkpoint_id", latest_id),
            runtime_id=data.get("runtime_id", runtime_id),
            mission_id=data.get("mission_id", ""),
            timestamp=data.get("timestamp", ""),
            runtime_status=data.get("runtime_status", "RUNNING"),
            completed_nodes=data.get("completed_nodes", []),
            pending_nodes=data.get("pending_nodes", []),
            failed_nodes=data.get("failed_nodes", []),
            results_reference=data.get("results_reference", {}),
            verification_state=data.get("verification_state", {}),
            retry_state=data.get("retry_state", {}),
            correlation_id=data.get("correlation_id", ""),
        )
        self._cache[latest_id] = chk
        return chk

    async def list_checkpoints(self, runtime_id: str) -> List[MissionCheckpoint]:
        runtime_index_key = f"runtime_checkpoints:{runtime_id}"
        index = await self._engine.read(runtime_index_key) or []

        res: List[MissionCheckpoint] = []
        for chk_id in index:
            if chk_id in self._cache:
                res.append(self._cache[chk_id])
            else:
                data = await self._engine.read(f"checkpoint:{chk_id}")
                if data:
                    res.append(MissionCheckpoint(
                        checkpoint_id=data.get("checkpoint_id", chk_id),
                        runtime_id=data.get("runtime_id", runtime_id),
                        mission_id=data.get("mission_id", ""),
                        timestamp=data.get("timestamp", ""),
                        runtime_status=data.get("runtime_status", "RUNNING"),
                        completed_nodes=data.get("completed_nodes", []),
                        pending_nodes=data.get("pending_nodes", []),
                        failed_nodes=data.get("failed_nodes", []),
                        results_reference=data.get("results_reference", {}),
                        verification_state=data.get("verification_state", {}),
                        retry_state=data.get("retry_state", {}),
                        correlation_id=data.get("correlation_id", ""),
                    ))
        return res

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        key = f"checkpoint:{checkpoint_id}"
        if checkpoint_id in self._cache:
            del self._cache[checkpoint_id]
        return await self._engine.delete(key)
