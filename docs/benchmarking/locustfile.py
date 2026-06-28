from locust import HttpUser, task, between

class FastApiUser(HttpUser):
    # Wait between 0.1 and 0.5 seconds between tasks
    wait_time = between(0.1, 0.5)

    @task(3)
    def health_check(self):
        self.client.get("/health")

    @task(1)
    def docs(self):
        self.client.get("/docs")
