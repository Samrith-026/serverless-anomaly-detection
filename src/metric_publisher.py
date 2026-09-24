"""Validated CloudWatch custom-metric publisher Lambda."""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any


VALID_NAME = re.compile(r"^[A-Za-z0-9_.\-/]{1,255}$")
VALID_UNITS = {
    "Seconds", "Microseconds", "Milliseconds", "Bytes", "Kilobytes", "Megabytes", "Gigabytes",
    "Terabytes", "Bits", "Kilobits", "Megabits", "Gigabits", "Terabits", "Percent", "Count",
    "Bytes/Second", "Kilobytes/Second", "Megabytes/Second", "Gigabytes/Second", "Terabytes/Second",
    "Bits/Second", "Kilobits/Second", "Megabits/Second", "Gigabits/Second", "Terabits/Second",
    "Count/Second", "None",
}


def _cloudwatch_text(value: Any, field: str, max_length: int, *, forbid_colon: bool = False) -> str:
    text = str(value)
    if not text.strip() or len(text) > max_length:
        raise ValueError(f"{field} must contain 1 to {max_length} characters")
    if forbid_colon and ":" in text:
        raise ValueError(f"{field} cannot contain a colon")
    try:
        text.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} must contain ASCII characters only") from error
    return text


def validate_namespace(value: str) -> str:
    namespace = _cloudwatch_text(value, "METRIC_NAMESPACE", 255, forbid_colon=True)
    if namespace.startswith("AWS/"):
        raise ValueError("METRIC_NAMESPACE cannot use the reserved AWS/ prefix")
    return namespace


def parse_event(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    name = str(body.get("metric_name", ""))
    if not VALID_NAME.fullmatch(name):
        raise ValueError("metric_name contains unsupported characters")
    try:
        value = float(body["value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("value must be numeric") from error
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    unit = str(body.get("unit", "None"))
    if unit not in VALID_UNITS:
        raise ValueError("unit is not a CloudWatch standard unit")
    raw_dimensions = body.get("dimensions", {})
    if not isinstance(raw_dimensions, dict) or len(raw_dimensions) > 30:
        raise ValueError("dimensions must be an object with at most 30 entries")
    dimensions = [
        {
            "Name": _cloudwatch_text(key, "dimension name", 255, forbid_colon=True),
            "Value": _cloudwatch_text(value, "dimension value", 1024),
        }
        for key, value in sorted(raw_dimensions.items(), key=lambda item: str(item[0]))
    ]
    return {"name": name, "value": value, "unit": unit, "dimensions": dimensions}


def handler(event: dict[str, Any], _context: Any, cloudwatch_client: Any = None) -> dict[str, Any]:
    metric = parse_event(event)
    if cloudwatch_client is None:
        import boto3

        cloudwatch_client = boto3.client("cloudwatch")
    namespace = validate_namespace(os.environ.get("METRIC_NAMESPACE", "Portfolio/Operations"))
    cloudwatch_client.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric["name"],
            "Value": metric["value"],
            "Unit": metric["unit"],
            "Dimensions": metric["dimensions"],
            "StorageResolution": 60,
        }],
    )
    return {"statusCode": 202, "body": json.dumps({"status": "accepted", "namespace": namespace})}
