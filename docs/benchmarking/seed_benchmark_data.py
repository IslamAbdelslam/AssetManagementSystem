"""
Seed script for generating 100,000 assets distributed across 5 organizations.
Used for aggressive benchmarking.
Run this using: docker compose exec app python docs/benchmarking/seed_benchmark_data.py
"""
import asyncio
import uuid
import random
from app.database import get_session_factory
from app.auth.models import Organization, User
from app.auth.service import hash_password
from app.assets.models import Asset
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

async def seed():
    factory = get_session_factory()
    async with factory() as db:
        print("Starting seed process...")
        # Clear existing benchmark data if needed
        # We will create 5 orgs explicitly
        orgs = []
        for i in range(5):
            org_id = uuid.uuid4()
            org = Organization(
                id=org_id,
                name=f"Benchmark Org {i}",
                slug=f"bench-org-{i}"
            )
            db.add(org)
            orgs.append(org)

            user = User(
                org_id=org.id,
                email=f"admin@{org.slug}.com",
                hashed_password=hash_password("BenchmarkPass123!"),
                role="admin"
            )
            db.add(user)
        
        await db.flush()
        print("Created 5 benchmark organizations and admin users.")

        asset_types = ["domain", "subdomain", "ip_address", "service", "certificate", "technology"]
        
        total_assets = 100_000
        assets_per_org = total_assets // len(orgs)

        batch_size = 5000
        for org in orgs:
            print(f"Seeding {assets_per_org} assets for org {org.slug}...")
            assets = []
            for j in range(assets_per_org):
                asset = Asset(
                    id=uuid.uuid4(),
                    org_id=org.id,
                    type=random.choice(asset_types),
                    value=f"asset-{org.slug}-{j}-{uuid.uuid4().hex[:8]}.com",
                    status="active",
                    source="import",
                    tags=["benchmark"],
                    metadata_={"benchmark_index": j}
                )
                assets.append(asset)

                if len(assets) >= batch_size:
                    db.add_all(assets)
                    await db.flush()
                    assets = []
            
            if assets:
                db.add_all(assets)
                await db.flush()
        
        await db.commit()
        print("Seed process completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
