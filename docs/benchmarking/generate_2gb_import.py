"""
Script to generate a massive 2+ GB JSON payload for testing the bulk import endpoint.
Runs completely streaming so it won't crash your RAM.
"""
import uuid
import random
import os

def generate_2gb_payload(filename="docs/benchmarking/massive_bulk_import.json"):
    target_size = 2 * 1024 * 1024 * 1024  # 2 GB
    asset_types = ["domain", "subdomain", "ip_address", "service", "certificate", "technology"]
    
    print(f"Starting generation of 2GB bulk import payload to {filename}...")
    
    # Write directly to disk to avoid MemoryError
    with open(filename, "w", encoding="utf-8") as f:
        f.write('{"records": [\n')
        
        first = True
        count = 0
        
        while True:
            # Adding a 2KB padding string to each record to reach 2GB faster
            # without needing 20 million rows (which might take too long to just generate).
            # This simulates an asset with very heavy metadata.
            record_str = '{"type": "%s", "value": "asset-%s.com", "source": "import", "tags": ["massive-bench"], "metadata": {"heavy_payload": "%s"}}' % (
                random.choice(asset_types),
                uuid.uuid4().hex,
                "x" * 2000
            )
            
            if not first:
                f.write(",\n")
            else:
                first = False
                
            f.write(record_str)
            count += 1
            
            # Check file size every 10,000 records to avoid slow I/O blocks on f.tell()
            if count % 10000 == 0:
                current_size = f.tell()
                print(f"Generated {count} records, current size: {current_size / 1024 / 1024:.2f} MB")
                if current_size >= target_size:
                    break
                
        f.write('\n]}')
        
    final_size = os.path.getsize(filename) / (1024 * 1024 * 1024)
    print(f"Done! Generated {count} records.")
    print(f"Final file size: {final_size:.2f} GB")

if __name__ == "__main__":
    # Ensure directory exists
    os.makedirs("docs/benchmarking", exist_ok=True)
    generate_2gb_payload()
