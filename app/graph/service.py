"""Graph BFS traversal service."""
from __future__ import annotations

import uuid
from collections import deque

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.models import Asset, AssetRelationship
from app.assets.schemas import GraphEdge, GraphNode, GraphResponse


class GraphService:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID) -> None:
        self.db = db
        self.org_id = org_id

    async def get_graph(self, root_id: uuid.UUID, depth: int = 2) -> GraphResponse:
        """BFS from root_id up to `depth` hops. Returns deduplicated nodes + edges."""
        depth = min(max(depth, 1), 5)  # clamp 1–5

        visited_ids: set[uuid.UUID] = set()
        queue: deque[tuple[uuid.UUID, int]] = deque([(root_id, 0)])
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        while queue:
            current_id, current_depth = queue.popleft()
            if current_id in visited_ids:
                continue
            visited_ids.add(current_id)

            # Fetch asset
            result = await self.db.execute(
                select(Asset).where(Asset.id == current_id, Asset.org_id == self.org_id)
            )
            asset = result.scalar_one_or_none()
            if not asset:
                continue

            nodes[str(current_id)] = GraphNode(
                id=str(asset.id),
                type=asset.type,
                value=asset.value,
                status=asset.status,
            )

            if current_depth >= depth:
                continue

            # Fetch all relationships for this asset
            rel_result = await self.db.execute(
                select(AssetRelationship).where(
                    AssetRelationship.org_id == self.org_id,
                    or_(
                        AssetRelationship.source_id == current_id,
                        AssetRelationship.target_id == current_id,
                    ),
                )
            )
            for rel in rel_result.scalars().all():
                edge_key = f"{rel.source_id}:{rel.target_id}:{rel.rel_type}"
                edges.append(
                    GraphEdge(
                        source=str(rel.source_id),
                        target=str(rel.target_id),
                        rel_type=rel.rel_type,
                    )
                )
                neighbor_id = rel.target_id if rel.source_id == current_id else rel.source_id
                if neighbor_id not in visited_ids:
                    queue.append((neighbor_id, current_depth + 1))

        # Deduplicate edges
        seen_edges: set[str] = set()
        unique_edges = []
        for e in edges:
            key = f"{e.source}:{e.target}:{e.rel_type}"
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return GraphResponse(
            nodes=list(nodes.values()),
            edges=unique_edges,
            depth=depth,
        )

    async def get_all_graph_data(self) -> GraphResponse:
        """Fetch all assets + relationships for org (used by D3 viz)."""
        assets_result = await self.db.execute(
            select(Asset).where(Asset.org_id == self.org_id)
        )
        assets = assets_result.scalars().all()

        rels_result = await self.db.execute(
            select(AssetRelationship).where(AssetRelationship.org_id == self.org_id)
        )
        rels = rels_result.scalars().all()

        nodes = [
            GraphNode(id=str(a.id), type=a.type, value=a.value, status=a.status)
            for a in assets
        ]
        edges = [
            GraphEdge(source=str(r.source_id), target=str(r.target_id), rel_type=r.rel_type)
            for r in rels
        ]
        return GraphResponse(nodes=nodes, edges=edges, depth=0)
