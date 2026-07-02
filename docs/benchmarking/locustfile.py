from locust import HttpUser, task, between, events
import random
import uuid
import requests

# Pre-fetch tokens for all 5 orgs so we don't DDoS the bcrypt login endpoint
ORG_TOKENS = []

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Pre-fetching auth tokens for 5 organizations...")
    host = environment.host or "http://localhost:8000"
    for i in range(5):
        email = f"admin@bench-org-{i}.com"
        try:
            resp = requests.post(f"{host}/api/v1/auth/login", json={
                "email": email,
                "password": "BenchmarkPass123!"
            })
            if resp.status_code == 200:
                ORG_TOKENS.append({
                    "slug": f"bench-org-{i}",
                    "token": resp.json().get("access_token")
                })
                print(f"Got token for {email}")
            else:
                print(f"Failed to get token for {email}: {resp.status_code}")
        except Exception as e:
            print(f"Error fetching token: {e}")

class BenchmarkUser(HttpUser):
    # Very short wait time to generate aggressive load
    wait_time = between(0.01, 0.1)

    def on_start(self):
        """Executed when a simulated user starts. Just pick a pre-fetched token."""
        if not ORG_TOKENS:
            self.token = None
            self.headers = {}
            return
            
        org_data = random.choice(ORG_TOKENS)
        self.token = org_data["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.org_slug = org_data["slug"]

    @task(5)
    def list_assets(self):
        """Read workload: List assets with pagination."""
        if not self.token: return
        self.client.get(
            "/api/v1/assets?limit=50&offset=0",
            headers=self.headers,
            name="/api/v1/assets (List)"
        )

    @task(2)
    def create_asset(self):
        """Write workload: Upsert an asset."""
        if not self.token: return
        self.client.post(
            "/api/v1/assets",
            headers=self.headers,
            json={
                "type": "domain",
                "value": f"bench-test-{uuid.uuid4().hex[:8]}.com",
                "source": "import",
                "tags": ["locust"]
            },
            name="/api/v1/assets (Create)"
        )

    @task(3)
    def get_stats(self):
        """Read workload: Aggregate stats."""
        if not self.token: return
        self.client.get(
            "/api/v1/assets/stats",
            headers=self.headers,
            name="/api/v1/assets/stats"
        )

    @task(1)
    def graph_traversal(self):
        """Heavy Read Workload: Graph Traversal."""
        if not self.token: return
        self.client.get(
            "/api/v1/graph/data",
            headers=self.headers,
            name="/api/v1/graph/data"
        )
