"""Send a stable series and a spike to the local anomaly detector."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen


BASE_URL = "http://localhost:8002"


def request(path: str, payload: dict | None = None) -> dict | list:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urlopen(Request(f"{BASE_URL}{path}", data=body, headers=headers), timeout=5) as response:
        return json.load(response)


def main() -> None:
    print("health:", request("/health"))
    for value in (100, 101, 99, 100, 100, 250):
        result = request(
            "/metrics",
            {
                "metric_name": "PipelineLatency",
                "value": value,
                "unit": "Milliseconds",
                "dimensions": {"Service": "orders"},
            },
        )
        print(f"value={value} anomaly={result['anomaly']}")
    print("alerts:", request("/alerts"))


if __name__ == "__main__":
    main()

