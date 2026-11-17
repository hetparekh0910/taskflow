"""Realistic mixed workload against a seeded TaskFlow.  Run:
    locust -f loadtest/locustfile.py --host http://localhost:8000 --headless -u 30 -r 5 -t 60s --csv loadtest/results
Mix: board loads and issue lists (reads, 80%), plus creating issues, drag-moves and comments (writes, 20%)."""
import random

from locust import HttpUser, between, task

WS = "acme-robotics"


class Member(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        r = self.client.post("/api/auth/login/", json={"email": "carol@acme.test", "password": "demo12345"}, name="POST /auth/login")
        self.client.headers["Authorization"] = f"Bearer {r.json()['access']}"
        projects = self.client.get(f"/api/w/{WS}/projects/", name="GET /projects").json()["results"]
        self.web = next(p for p in projects if p["key"] == "WEB")["id"]
        self.my_issues = []

    @task(6)
    def board(self):
        self.client.get(f"/api/w/{WS}/projects/{self.web}/board/", name="GET /projects/:id/board")

    @task(4)
    def issues_list(self):
        self.client.get(f"/api/w/{WS}/issues/?project={self.web}&q=a", name="GET /issues (filtered)")

    @task(2)
    def dashboard(self):
        self.client.get(f"/api/w/{WS}/dashboard/", name="GET /dashboard")

    @task(1)
    def create_issue(self):
        r = self.client.post(f"/api/w/{WS}/issues/", json={"project": self.web, "title": "load test issue"}, name="POST /issues")
        if r.ok:
            self.my_issues.append(r.json())

    @task(2)
    def move(self):
        if not self.my_issues:
            return
        issue = random.choice(self.my_issues)
        board = self.client.get(f"/api/w/{WS}/projects/{self.web}/board/", name="GET /projects/:id/board").json()
        target = random.choice([c for c in board["columns"] if c["status"]["name"] in ("To Do", "In Progress", "In Review")])
        self.client.post(f"/api/w/{WS}/issues/{issue['id']}/move/", json={"status": target["status"]["id"]}, name="POST /issues/:id/move")

    @task(1)
    def comment(self):
        if self.my_issues:
            self.client.post(f"/api/w/{WS}/comments/", json={"issue": random.choice(self.my_issues)["id"], "body": "load test"}, name="POST /comments")
