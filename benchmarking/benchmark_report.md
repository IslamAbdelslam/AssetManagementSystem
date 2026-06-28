# Bulk Import Benchmark Report

This benchmark tests the end-to-end performance of the `/api/v1/assets/bulk-import` endpoint, which asynchronously processes large lists of assets using Celery workers and PostgreSQL `ON CONFLICT DO UPDATE` upserts.

### Worker Specifications
- **Celery Concurrency**: 4 workers
- **Payload Batching**: 4 jobs of 25,000 assets each (total 100,000 assets)

### Per-Job Results

| Job ID      | Status   |   Imported |   Errors | Submit Time   | Processing Time   |   Throughput (assets/sec) |
|-------------|----------|------------|----------|---------------|-------------------|---------------------------|
| 4792c8b3... | done     |     10,000 |        0 | 0.21s         | 62.51s            |                    159.96 |
| cdd54382... | done     |     10,000 |        0 | 0.10s         | 65.00s            |                    153.86 |
| 6940baef... | done     |     10,000 |        0 | 0.17s         | 63.27s            |                    158.05 |
| bb71b7b0... | done     |     10,000 |        0 | 0.10s         | 65.40s            |                    152.91 |
| 0c2eb561... | done     |     10,000 |        0 | 0.15s         | 64.72s            |                    154.52 |
| 0646d581... | done     |     10,000 |        0 | 0.19s         | 65.40s            |                    152.9  |
| 84c581eb... | done     |     10,000 |        0 | 0.15s         | 69.32s            |                    144.25 |
| e2663c44... | done     |     10,000 |        0 | 0.13s         | 73.36s            |                    136.31 |
| b3af99d0... | done     |     10,000 |        0 | 0.18s         | 72.74s            |                    137.49 |
| 6eed2c8a... | done     |     10,000 |        0 | 0.11s         | 73.02s            |                    136.95 |
| 23f72fb3... | done     |     10,000 |        0 | 0.15s         | 73.44s            |                    136.17 |
| 610a5242... | done     |     10,000 |        0 | 0.27s         | 73.44s            |                    136.17 |
| bde4935c... | done     |     10,000 |        0 | 0.17s         | 73.00s            |                    136.98 |
| fdbb43b5... | done     |     10,000 |        0 | 0.18s         | 73.36s            |                    136.31 |
| c685967c... | done     |     10,000 |        0 | 0.31s         | 73.36s            |                    136.32 |
| c65d5402... | done     |     10,000 |        0 | 0.13s         | 75.09s            |                    133.18 |
| 3a4b15ed... | done     |     10,000 |        0 | 0.18s         | 75.37s            |                    132.68 |
| 702c3e88... | done     |     10,000 |        0 | 1.33s         | 75.03s            |                    133.27 |
| 23398abc... | done     |     10,000 |        0 | 1.72s         | 74.84s            |                    133.61 |
| daf05b9a... | done     |     10,000 |        0 | 1.35s         | 75.37s            |                    132.68 |

### Global Performance Summary

- **Total Assets Processed**: 200,000
- **Total Wall-clock Time**: 75.37 seconds
- **Global Throughput**: **2653.60 assets/second**
