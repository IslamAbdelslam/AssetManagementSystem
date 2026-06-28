import asyncio
import httpx
import json

async def main():
    base_url = "http://localhost:8000/api/v1"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Register a user
        org_payload = {
            "org": {"name": "Test Org", "slug": "test-org"},
            "email": "test@test.com",
            "password": "Password123!"
        }
        resp = await client.post(f"{base_url}/auth/register", json=org_payload)
        
        # Login
        login_payload = {
            "email": "test@test.com",
            "password": "Password123!"
        }
        resp = await client.post(f"{base_url}/auth/login", json=login_payload)
        data = resp.json()
        token = data.get("access_token")
        
        if not token:
            print("Login failed:", data)
            return

        headers = {"Authorization": f"Bearer {token}"}
        
        # We need to make sure there are assets. Let's add some.
        assets = [
            {"type": "domain", "value": "test-stale.com", "status": "stale", "source": "manual", "tags": ["prod"]},
            {"type": "certificate", "value": "test-cert", "status": "stale", "source": "scan", "tags": ["prod"]},
            {"type": "subdomain", "value": "api.test.com", "status": "active", "source": "scan", "tags": ["prod"]}
        ]
        
        for a in assets:
            await client.post(f"{base_url}/assets", json=a, headers=headers)
        
        # Now let's query the AI
        print("--- Testing Example 1: 'show me all stale certificates' ---")
        query_payload = {"query": "show me all stale certificates"}
        resp = await client.post(f"{base_url}/ai/query", json=query_payload, headers=headers)
        print("Status:", resp.status_code)
        print(json.dumps(resp.json(), indent=2))
        
        print("\n--- Testing Example 2: 'find all assets tagged production' ---")
        query_payload = {"query": "find all assets tagged production"}
        resp = await client.post(f"{base_url}/ai/query", json=query_payload, headers=headers)
        print("Status:", resp.status_code)
        print(json.dumps(resp.json(), indent=2))
        
        print("\n--- Testing Summarize ---")
        query_payload = {"query": "summarize our attack surface", "focus": "general"}
        resp = await client.post(f"{base_url}/ai/summarize", json=query_payload, headers=headers)
        print("Status:", resp.status_code)
        print(json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
