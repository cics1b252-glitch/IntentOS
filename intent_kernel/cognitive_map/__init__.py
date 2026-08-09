"""Cognitive Map — Interactive Knowledge Graph.

Visual representation of connections between:
- Knowledge events
- Decisions
- Projects
- People
- Documents
- Modules
- Domains

The signature visual of Intent OS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MapNode:
    """A node in the cognitive graph."""
    id: str
    label: str
    node_type: str  # knowledge, decision, project, document, person, module, domain
    domain: str = ""
    size: float = 10.0
    color: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class MapEdge:
    """An edge in the cognitive graph."""
    source: str
    target: str
    edge_type: str = "related"  # related, caused_by, part_of, depends_on
    weight: float = 1.0


class CognitiveMap:
    """Interactive cognitive map of the Knowledge Core.

    Generates a graph visualization showing how knowledge connects.
    """

    def __init__(self, kernel: Any = None):
        self.kernel = kernel

    @property
    def name(self) -> str:
        return "cognitive_map"

    async def generate(
        self,
        domain_filter: str | None = None,
        type_filter: str | None = None,
        limit: int = 200,
    ) -> dict:
        """Generate the cognitive map graph."""
        nodes = []
        edges = []

        if not self.kernel:
            return {"nodes": nodes, "edges": edges, "stats": {}}

        try:
            from intent_kernel.types import QueryFilters

            filters = QueryFilters(limit=limit)
            if domain_filter:
                from intent_kernel.types import Domain
                filters.domain = Domain(domain_filter)

            events = await self.kernel.knowledge.query(filters)

            # Create nodes from events
            for event in events:
                if type_filter and event.type.value != type_filter:
                    continue

                node = MapNode(
                    id=event.id,
                    label=event.title[:40],
                    node_type=event.type.value,
                    domain=event.domain.value,
                    size=max(5, event.confidence * 25),
                    color=self._get_color(event.type.value),
                    metadata={
                        "confidence": event.confidence,
                        "lifecycle": event.lifecycle.value,
                        "source": event.source,
                    },
                )
                nodes.append(node)

            # Create edges (domain connections + type relationships)
            node_ids = {n.id for n in nodes}
            for i, n1 in enumerate(nodes):
                for n2 in nodes[i+1:]:
                    # Same domain = connection
                    if n1.domain == n2.domain and n1.domain:
                        edges.append(MapEdge(
                            source=n1.id,
                            target=n2.id,
                            edge_type="same_domain",
                            weight=0.5,
                        ))
                    # Same type = weaker connection
                    elif n1.node_type == n2.node_type:
                        edges.append(MapEdge(
                            source=n1.id,
                            target=n2.id,
                            edge_type="same_type",
                            weight=0.3,
                        ))

            # Deduplicate edges
            seen = set()
            unique_edges = []
            for e in edges:
                key = tuple(sorted([e.source, e.target]))
                if key not in seen:
                    seen.add(key)
                    unique_edges.append(e)

            edges = unique_edges[:500]  # limit edges

        except Exception:
            pass

        # Stats
        type_counts = {}
        domain_counts = {}
        for n in nodes:
            type_counts[n.node_type] = type_counts.get(n.node_type, 0) + 1
            if n.domain:
                domain_counts[n.domain] = domain_counts.get(n.domain, 0) + 1

        return {
            "nodes": [
                {"id": n.id, "label": n.label, "type": n.node_type,
                 "domain": n.domain, "size": n.size, "color": n.color}
                for n in nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target,
                 "type": e.edge_type, "weight": e.weight}
                for e in edges
            ],
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "by_type": type_counts,
                "by_domain": domain_counts,
            },
        }

    async def search(self, query: str, limit: int = 50) -> dict:
        """Search the cognitive map."""
        nodes = []
        if self.kernel:
            try:
                from intent_kernel.types import QueryFilters
                events = await self.kernel.knowledge.query(
                    QueryFilters(search_text=query, limit=limit)
                )
                for e in events:
                    nodes.append({
                        "id": e.id,
                        "label": e.title[:40],
                        "type": e.type.value,
                        "domain": e.domain.value,
                        "confidence": e.confidence,
                    })
            except Exception:
                pass

        return {"query": query, "results": nodes, "total": len(nodes)}

    async def get_node_details(self, node_id: str) -> dict | None:
        """Get full details of a specific node."""
        if not self.kernel:
            return None
        try:
            event = await self.kernel.knowledge.store.get(node_id)
            if event:
                return {
                    "id": event.id,
                    "type": event.type.value,
                    "domain": event.domain.value,
                    "title": event.title,
                    "content": event.content,
                    "confidence": event.confidence,
                    "lifecycle": event.lifecycle.value,
                    "source": event.source,
                    "tags": event.tags,
                    "created_at": event.created_at.isoformat() if hasattr(event.created_at, 'isoformat') else str(event.created_at),
                }
        except Exception:
            pass
        return None

    async def get_stats(self) -> dict:
        """Get map statistics."""
        if not self.kernel:
            return {"total_events": 0}

        try:
            from intent_kernel.types import QueryFilters
            events = await self.kernel.knowledge.query(QueryFilters(limit=10000))
            domains = {}
            types = {}
            for e in events:
                domains[e.domain.value] = domains.get(e.domain.value, 0) + 1
                types[e.type.value] = types.get(e.type.value, 0) + 1
            return {
                "total_events": len(events),
                "domains": domains,
                "types": types,
                "unique_domains": len(domains),
                "unique_types": len(types),
            }
        except Exception:
            return {"total_events": 0}

    def _get_color(self, node_type: str) -> str:
        """Color by node type."""
        colors = {
            "decision": "#6366f1",    # indigo
            "fact": "#22c55e",        # green
            "insight": "#eab308",     # yellow
            "goal": "#ef4444",        # red
            "architecture": "#8b5cf6", # violet
            "rfc": "#3b82f6",         # blue
            "memory": "#f97316",      # orange
            "lesson": "#14b8a6",      # teal
            "strategy": "#ec4899",    # pink
            "requirement": "#64748b", # slate
        }
        return colors.get(node_type, "#6b7280")  # default gray
