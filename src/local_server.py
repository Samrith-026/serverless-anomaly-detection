"""Local rolling-baseline anomaly detector and JSON API."""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from metric_publisher import parse_event


class AnomalyEngine:
    def __init__(
        self,
        window_size: int = 20,
        min_samples: int = 5,
        sensitivity: float = 2.0,
        history_limit: int = 1_000,
    ) -> None:
        if window_size < 2 or min_samples < 2 or min_samples > window_size or sensitivity <= 0 or history_limit < 1:
            raise ValueError("Invalid anomaly detector configuration")
        self.window_size = window_size
        self.min_samples = min_samples
        self.sensitivity = sensitivity
        self._windows: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window_size))
        self._observations: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._lock = threading.Lock()

    @staticmethod
    def _series_key(metric: dict[str, Any]) -> str:
        dimensions = ",".join(f"{d['Name']}={d['Value']}" for d in metric["dimensions"])
        return f"{metric['name']}|{dimensions}"

    def observe(self, payload: dict[str, Any]) -> dict[str, Any]:
        metric = parse_event(payload)
        key = self._series_key(metric)
        with self._lock:
            baseline = list(self._windows[key])
            mean = statistics.fmean(baseline) if baseline else None
            deviation = statistics.pstdev(baseline) if len(baseline) > 1 else None
            is_anomaly = False
            lower = upper = None
            if len(baseline) >= self.min_samples:
                spread = max((deviation or 0.0) * self.sensitivity, max(abs(mean or 0.0) * 0.01, 0.001))
                lower, upper = (mean or 0.0) - spread, (mean or 0.0) + spread
                is_anomaly = not lower <= metric["value"] <= upper
            observation = {
                "metric_name": metric["name"],
                "value": metric["value"],
                "unit": metric["unit"],
                "dimensions": metric["dimensions"],
                "anomaly": is_anomaly,
                "baseline_samples": len(baseline),
                "expected_lower": lower,
                "expected_upper": upper,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
            if is_anomaly:
                alert = {
                    "alert_id": str(uuid.uuid4()),
                    "state": "ALARM",
                    "reason": f"{metric['value']} is outside [{lower:.3f}, {upper:.3f}]",
                    **observation,
                }
                self._alerts.append(alert)
                observation["alert_id"] = alert["alert_id"]
            else:
                self._windows[key].append(metric["value"])
            self._observations.append(observation)
            return dict(observation)

    def observations(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._observations)

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._alerts)


ENGINE = AnomalyEngine(
    window_size=int(os.environ.get("ANOMALY_WINDOW_SIZE", "20")),
    min_samples=int(os.environ.get("ANOMALY_MIN_SAMPLES", "5")),
    sensitivity=float(os.environ.get("ANOMALY_SENSITIVITY", "2")),
    history_limit=int(os.environ.get("ANOMALY_HISTORY_LIMIT", "1000")),
)


class Handler(BaseHTTPRequestHandler):
    server_version = "AnomalyDetectionLocal/1.0"

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 1_000_000:
            raise ValueError("Request body must contain 1 to 1000000 bytes")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        routes = {
            "/health": lambda: {"status": "UP", "service": "anomaly-detection"},
            "/metrics": ENGINE.observations,
            "/alerts": ENGINE.alerts,
        }
        route = routes.get(self.path)
        self._json(HTTPStatus.OK, route()) if route else self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            if self.path == "/metrics":
                self._json(HTTPStatus.ACCEPTED, ENGINE.observe(self._body()))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, format_string: str, *args: Any) -> None:
        print(json.dumps({"service": "anomaly-detection", "message": format_string % args}))


def main() -> None:
    port = int(os.environ.get("PORT", "8002"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Anomaly detection local API listening on http://localhost:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
