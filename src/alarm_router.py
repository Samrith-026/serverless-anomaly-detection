"""Enrich CloudWatch alarm events and route them to SNS."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def normalize(event: dict[str, Any]) -> dict[str, Any]:
    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName")
    state = detail.get("state", {})
    if not alarm_name or not state.get("value"):
        raise ValueError("Unsupported CloudWatch alarm event")
    return {
        "alarm_name": alarm_name,
        "state": state["value"],
        "reason": state.get("reason", "No reason supplied"),
        "changed_at": state.get("timestamp", event.get("time")),
        "account": event.get("account"),
        "region": event.get("region"),
        "event_id": event.get("id"),
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }


def handler(event: dict[str, Any], _context: Any, sns_client: Any = None) -> dict[str, Any]:
    alert = normalize(event)
    if sns_client is None:
        import boto3

        sns_client = boto3.client("sns")
    topic_arn = os.environ.get("ALERT_TOPIC_ARN", "")
    if not topic_arn:
        raise RuntimeError("ALERT_TOPIC_ARN is required")
    response = sns_client.publish(
        TopicArn=topic_arn,
        Subject=f"[{alert['state']}] {alert['alarm_name']}"[:100],
        Message=json.dumps(alert, separators=(",", ":")),
        MessageAttributes={
            "alarm_state": {"DataType": "String", "StringValue": alert["state"]},
            "alarm_name": {"DataType": "String", "StringValue": alert["alarm_name"]},
        },
    )
    return {"message_id": response["MessageId"], "alarm": alert["alarm_name"]}
