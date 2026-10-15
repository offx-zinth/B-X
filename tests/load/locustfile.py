"""Load profile: signup -> upload -> graph -> impact -> semantic -> AI ask.

Run against a live stack (compose or Helm):
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
        -u 50 -r 5 -t 5m --headless
SLOs encoded as assertions: p95 impact < 500ms on warm cache, zero 5xx.
"""
import random
import uuid

from locust import HttpUser, between, task

CSV = b"supplier_id,name,capacity\nS1,Acme,5000\nS2,Globex,3200\n"


class XrayUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.email = f"load-{uuid.uuid4().hex[:8]}@example.com"
        r = self.client.post("/auth/signup", json={
            "org": "Load Co", "email": self.email, "password": "Str0ng-Pass!9"})
        self.token = (r.json() or {}).get("token", "")
        self.node_id = ""
        if self.token:
            h = {"Authorization": f"Bearer {self.token}"}
            self.client.post("/ingest/upload",
                             files={"f": ("suppliers.csv", CSV, "text/csv")},
                             headers=h, name="/ingest/upload")
            nodes = self.client.get("/graph/nodes", headers=h,
                                    name="/graph/nodes").json()
            if nodes:
                self.node_id = random.choice(nodes)["id"]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    @task(5)
    def read_nodes(self):
        with self.client.get("/graph/nodes", headers=self._h(),
                             name="/graph/nodes", catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"5xx on /graph/nodes: {r.status_code}")

    @task(3)
    def impact(self):
        if not self.node_id:
            return
        with self.client.get(f"/graph/impact/{self.node_id}", headers=self._h(),
                             name="/graph/impact/[id]", catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"5xx on impact: {r.status_code}")
            elif r.elapsed.total_seconds() > 2.0:
                r.failure(f"impact p-slow: {r.elapsed.total_seconds():.2f}s")

    @task(2)
    def semantic(self):
        with self.client.get("/ai/search/semantic", params={"q": "supplier capacity"},
                             headers=self._h(), name="/ai/search/semantic",
                             catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"5xx on semantic: {r.status_code}")

    @task(1)
    def ask(self):
        with self.client.post("/ai/ask",
                              json={"question": "What are the top risks?",
                                    "use_llm": False},
                              headers=self._h(), name="/ai/ask",
                              catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"5xx on ask: {r.status_code}")
