import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import alarm_router
import metric_publisher
from local_server import AnomalyEngine


class MetricPublisherTests(unittest.TestCase):
    def test_publishes_valid_metric(self):
        cloudwatch = Mock()
        event = {"metric_name": "PipelineLatency", "value": 125.5, "unit": "Milliseconds", "dimensions": {"Service": "orders"}}
        with patch.dict(os.environ, {"METRIC_NAMESPACE": "Demo/Ops"}, clear=True):
            response = metric_publisher.handler(event, None, cloudwatch)
        self.assertEqual(202, response["statusCode"])
        call = cloudwatch.put_metric_data.call_args.kwargs
        self.assertEqual("Demo/Ops", call["Namespace"])
        self.assertEqual(125.5, call["MetricData"][0]["Value"])

    def test_rejects_non_finite_metric(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            metric_publisher.parse_event({"metric_name": "Latency", "value": "NaN"})

    def test_rejects_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "colon"):
            metric_publisher.parse_event({"metric_name": "Latency", "value": 10, "dimensions": {"Bad:Name": "orders"}})

    def test_normalizes_dimension_order(self):
        result = metric_publisher.parse_event({
            "metric_name": "Latency",
            "value": 10,
            "dimensions": {"Zone": "a", "Service": "orders"},
        })
        self.assertEqual(["Service", "Zone"], [item["Name"] for item in result["dimensions"]])

    def test_rejects_reserved_namespace(self):
        with patch.dict(os.environ, {"METRIC_NAMESPACE": "AWS/EC2"}, clear=True):
            with self.assertRaisesRegex(ValueError, "reserved"):
                metric_publisher.handler({"metric_name": "Latency", "value": 10}, None, Mock())


class AlarmRouterTests(unittest.TestCase):
    def test_routes_alarm_to_sns(self):
        sns = Mock()
        sns.publish.return_value = {"MessageId": "message-1"}
        event = json.loads((Path(__file__).parents[1] / "fixtures" / "alarm_event.json").read_text())
        with patch.dict(os.environ, {"ALERT_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:alerts"}, clear=True):
            result = alarm_router.handler(event, None, sns)
        self.assertEqual("message-1", result["message_id"])
        self.assertIn("PipelineLatency", sns.publish.call_args.kwargs["Subject"])

    def test_rejects_unknown_shape(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            alarm_router.normalize({})

    def test_requires_topic_configuration(self):
        event = json.loads((Path(__file__).parents[1] / "fixtures" / "alarm_event.json").read_text())
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALERT_TOPIC_ARN"):
                alarm_router.handler(event, None, Mock())


class LocalAnomalyEngineTests(unittest.TestCase):
    def test_detects_spike_after_stable_baseline(self):
        engine = AnomalyEngine(window_size=10, min_samples=5, sensitivity=2)
        for value in (100, 101, 99, 100, 100):
            self.assertFalse(engine.observe({"metric_name": "Latency", "value": value})["anomaly"])
        result = engine.observe({"metric_name": "Latency", "value": 250})
        self.assertTrue(result["anomaly"])
        self.assertEqual(1, len(engine.alerts()))

    def test_keeps_dimension_series_separate(self):
        engine = AnomalyEngine(window_size=5, min_samples=2, sensitivity=2)
        first = engine.observe({"metric_name": "Latency", "value": 10, "dimensions": {"Service": "a"}})
        second = engine.observe({"metric_name": "Latency", "value": 500, "dimensions": {"Service": "b"}})
        self.assertEqual(0, first["baseline_samples"])
        self.assertEqual(0, second["baseline_samples"])

    def test_excludes_anomaly_from_learned_baseline(self):
        engine = AnomalyEngine(window_size=5, min_samples=2, sensitivity=2)
        engine.observe({"metric_name": "Latency", "value": 100})
        engine.observe({"metric_name": "Latency", "value": 100})
        self.assertTrue(engine.observe({"metric_name": "Latency", "value": 500})["anomaly"])
        self.assertFalse(engine.observe({"metric_name": "Latency", "value": 100})["anomaly"])

    def test_bounds_observation_and_alert_history(self):
        engine = AnomalyEngine(window_size=3, min_samples=2, sensitivity=1, history_limit=2)
        for value in (100, 100, 200, 300):
            engine.observe({"metric_name": "Latency", "value": value})
        self.assertEqual(2, len(engine.observations()))
        self.assertEqual(2, len(engine.alerts()))

    def test_rejects_invalid_configuration(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            AnomalyEngine(window_size=2, min_samples=3)


if __name__ == "__main__":
    unittest.main()
