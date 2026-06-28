import asyncio
import aiohttp
import os
import time
import uuid
import sys
from tabulate import tabulate


BASE_URL = "http://localhost:8000/api/v1"

async def authenticate(session):
    email = f"benchmark_{uuid.uuid4().hex[:6]}@example.com"
    password = "SuperSecretPassword1!"
    org_slug = f"bench-org-{uuid.uuid4().hex[:6]}"

    async with session.post(f"{BASE_URL}/auth/register", json={
        "email": email,
        "password": password,
        "org": {
            "name": f"Benchmark Org {uuid.uuid4().hex[:6]}",
            "slug": org_slug
        }
    }) as resp:
        if resp.status not in (200, 201):
            text = await resp.text()
            print(f"Failed to register: {resp.status} - {text}")
            return None

    async with session.post(f"{BASE_URL}/auth/login", json={
        "email": email,
        "password": password
    }) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data["access_token"]
        else:
            text = await resp.text()
            print(f"Failed to login: {resp.status} - {text}")
            return None

def generate_assets(num_assets=10000, batch_index=0):
    assets = []
    parent_id = f"domain_{batch_index}_0"
    assets.append({
        "id": parent_id,
        "type": "domain",
        "value": f"example{batch_index}.com",
        "status": "active",
        "source": "scan",
        "tags": ["root"],
        "metadata": {}
    })
    
    for i in range(1, num_assets):
        asset_id = f"asset_{batch_index}_{i}"
        if i % 2 == 0:
            assets.append({
                "id": asset_id,
                "type": "subdomain",
                "value": f"api{i}.example{batch_index}.com",
                "status": "active",
                "source": "scan",
                "tags": ["prod"],
                "metadata": {},
                "parent": parent_id
            })
        else:
            target = f"asset_{batch_index}_{i-1}" if i > 1 else parent_id
            assets.append({
                "id": asset_id,
                "type": "certificate",
                "value": f"CN=api{i}.example{batch_index}.com",
                "status": "active",
                "source": "scan",
                "tags": [],
                "metadata": {"issuer": "Let's Encrypt"},
                "covers": target
            })
    return assets

async def submit_job(session, token, records):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    async with session.post(f"{BASE_URL}/assets/bulk-import", json={"records": records}, headers=headers) as resp:
        elapsed = time.time() - start
        if resp.status == 202:
            data = await resp.json()
            return data["job_id"], elapsed
        else:
            text = await resp.text()
            print(f"Failed to submit job: {resp.status} - {text}")
            return None, elapsed

async def poll_job(session, token, job_id, submit_time):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    while True:
        async with session.get(f"{BASE_URL}/jobs/{job_id}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data["status"] in ("done", "failed"):
                    elapsed_processing = time.time() - start
                    total_elapsed = elapsed_processing + submit_time
                    return {
                        "job_id": job_id,
                        "status": data["status"],
                        "imported": data.get("imported", 0),
                        "errors": data.get("error_count", 0),
                        "time_submit": submit_time,
                        "time_process": elapsed_processing,
                        "time_total": total_elapsed,
                        "throughput": data.get("imported", 0) / elapsed_processing if elapsed_processing > 0 else 0
                    }
            else:
                text = await resp.text()
                print(f"Failed to poll {job_id}: {resp.status} - {text}")
                return None
        await asyncio.sleep(2)

async def main():
    print("=== Bulk Import Benchmark Suite ===")
    async with aiohttp.ClientSession() as session:
        print("[*] Authenticating...")
        token = await authenticate(session)
        if not token:
            sys.exit(1)
        
        NUM_JOBS = 20
        ASSETS_PER_JOB = 10000 
        TOTAL_ASSETS = NUM_JOBS * ASSETS_PER_JOB

        print(f"[*] Generating {TOTAL_ASSETS} assets across {NUM_JOBS} jobs to utilize all Celery workers...")
        job_infos = []
        for i in range(NUM_JOBS):
            records = generate_assets(ASSETS_PER_JOB, batch_index=i)
            print(f"    Submitting job {i+1}...")
            job_id, submit_time = await submit_job(session, token, records)
            if job_id:
                job_infos.append((job_id, submit_time))
            await asyncio.sleep(0.5)

        print(f"[*] Waiting for {len(job_infos)} jobs to complete asynchronously (polling via Redis)...")
        start_global = time.time()
        
        tasks = [poll_job(session, token, j_id, s_time) for j_id, s_time in job_infos]
        results = await asyncio.gather(*tasks)
        
        global_time = time.time() - start_global
        
        # Prepare table
        table_data = []
        total_imported = 0
        total_errors = 0
        for r in results:
            if r:
                table_data.append([
                    r['job_id'][:8] + "...", 
                    r['status'], 
                    f"{r['imported']:,}", 
                    r['errors'], 
                    f"{r['time_submit']:.2f}s", 
                    f"{r['time_process']:.2f}s", 
                    f"{r['throughput']:.2f}"
                ])
                total_imported += r['imported']
                total_errors += r['errors']

        headers = ["Job ID", "Status", "Imported", "Errors", "Submit Time", "Processing Time", "Throughput (assets/sec)"]
        
        print("\n=== Benchmark Results ===")
        print(tabulate(table_data, headers=headers, tablefmt="github"))
        
        print("\n=== Summary ===")
        print(f"Total Assets Processed : {total_imported:,}")
        print(f"Total Errors           : {total_errors:,}")
        print(f"Total Wall-clock Time  : {global_time:.2f} seconds")
        print(f"Global Throughput      : {total_imported / global_time:.2f} assets/second")
        
        # Save to markdown report
        report_path = os.path.join(os.path.dirname(__file__), "benchmark_report.md")
        with open(report_path, "w") as f:
            f.write("# Bulk Import Benchmark Report\n\n")
            f.write("This benchmark tests the end-to-end performance of the `/api/v1/assets/bulk-import` endpoint, which asynchronously processes large lists of assets using Celery workers and PostgreSQL `ON CONFLICT DO UPDATE` upserts.\n\n")
            f.write("### Worker Specifications\n")
            f.write("- **Celery Concurrency**: 4 workers\n")
            f.write("- **Payload Batching**: 4 jobs of 25,000 assets each (total 100,000 assets)\n\n")
            f.write("### Per-Job Results\n\n")
            f.write(tabulate(table_data, headers=headers, tablefmt="github"))
            f.write("\n\n### Global Performance Summary\n\n")
            f.write(f"- **Total Assets Processed**: {total_imported:,}\n")
            f.write(f"- **Total Wall-clock Time**: {global_time:.2f} seconds\n")
            f.write(f"- **Global Throughput**: **{total_imported / global_time:.2f} assets/second**\n")

if __name__ == "__main__":
    asyncio.run(main())
