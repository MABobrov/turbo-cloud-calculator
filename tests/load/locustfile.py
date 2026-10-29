"""Нагрузочный сценарий для REST API (locust).

Запуск: locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000
"""

import json
from pathlib import Path

from locust import HttpUser, between, task

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
CONFIGS = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EXAMPLES.glob("*.json"))]


class CalculatorUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(8)
    def estimate(self) -> None:
        for config in CONFIGS:
            self.client.post("/v1/estimate", json=config, name="/v1/estimate")

    @task(1)
    def pricelist(self) -> None:
        self.client.get("/v1/pricelist?category=vm", name="/v1/pricelist")

    @task(1)
    def health(self) -> None:
        self.client.get("/health")
