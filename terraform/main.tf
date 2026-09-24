locals { name_prefix = var.name_prefix }

data "archive_file" "publisher" {
  type        = "zip"
  source_file = "${path.module}/../src/metric_publisher.py"
  output_path = "${path.module}/metric-publisher.zip"
}

data "archive_file" "router" {
  type        = "zip"
  source_file = "${path.module}/../src/alarm_router.py"
  output_path = "${path.module}/alarm-router.zip"
}

resource "aws_sns_topic" "alerts" {
  name              = "${local.name_prefix}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sqs_queue" "alarm_dead_letter" {
  name                      = "${local.name_prefix}-eventbridge-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

resource "aws_iam_role" "publisher" {
  name               = "${local.name_prefix}-publisher-role"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role" "router" {
  name               = "${local.name_prefix}-router-role"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_cloudwatch_log_group" "publisher" {
  name              = "/aws/lambda/${local.name_prefix}-metric-publisher"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "router" {
  name              = "/aws/lambda/${local.name_prefix}-alarm-router"
  retention_in_days = 30
}

resource "aws_iam_role_policy" "publisher" {
  role = aws_iam_role.publisher.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = var.metric_namespace } } },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.publisher.arn}:*" }
  ] })
}

resource "aws_iam_role_policy" "router" {
  role = aws_iam_role.router.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["sns:Publish"], Resource = aws_sns_topic.alerts.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.router.arn}:*" }
  ] })
}

resource "aws_lambda_function" "publisher" {
  function_name                  = "${local.name_prefix}-metric-publisher"
  role                           = aws_iam_role.publisher.arn
  runtime                        = "python3.12"
  handler                        = "metric_publisher.handler"
  filename                       = data.archive_file.publisher.output_path
  source_code_hash               = data.archive_file.publisher.output_base64sha256
  timeout                        = 10
  memory_size                    = 128
  reserved_concurrent_executions = 5
  environment { variables = { METRIC_NAMESPACE = var.metric_namespace } }
  depends_on = [aws_cloudwatch_log_group.publisher, aws_iam_role_policy.publisher]
}

resource "aws_lambda_function" "router" {
  function_name                  = "${local.name_prefix}-alarm-router"
  role                           = aws_iam_role.router.arn
  runtime                        = "python3.12"
  handler                        = "alarm_router.handler"
  filename                       = data.archive_file.router.output_path
  source_code_hash               = data.archive_file.router.output_base64sha256
  timeout                        = 10
  memory_size                    = 128
  reserved_concurrent_executions = 5
  environment { variables = { ALERT_TOPIC_ARN = aws_sns_topic.alerts.arn } }
  depends_on = [aws_cloudwatch_log_group.router, aws_iam_role_policy.router]
}

resource "aws_cloudwatch_metric_alarm" "anomaly" {
  alarm_name          = "${local.name_prefix}-${var.metric_name}-anomaly"
  alarm_description   = "Alerts when ${var.metric_name} moves outside its learned normal band."
  comparison_operator = "LessThanLowerOrGreaterThanUpperThreshold"
  evaluation_periods  = 2
  threshold_metric_id = "ad1"
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "ad1"
    expression  = "ANOMALY_DETECTION_BAND(m1, ${var.anomaly_band_width})"
    label       = "Expected ${var.metric_name}"
    return_data = true
  }

  metric_query {
    id          = "m1"
    return_data = false
    metric {
      metric_name = var.metric_name
      namespace   = var.metric_namespace
      period      = 60
      stat        = "Average"
      unit        = var.metric_unit
      dimensions  = { Service = var.service_dimension }
    }
  }
}

resource "aws_cloudwatch_event_rule" "alarm" {
  name = "${local.name_prefix}-alarm-state-change"
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.anomaly.alarm_name]
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "router" {
  rule       = aws_cloudwatch_event_rule.alarm.name
  arn        = aws_lambda_function.router.arn
  depends_on = [aws_sqs_queue_policy.eventbridge_dead_letter]
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }
  dead_letter_config {
    arn = aws_sqs_queue.alarm_dead_letter.arn
  }
}

data "aws_iam_policy_document" "eventbridge_dead_letter" {
  statement {
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.alarm_dead_letter.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.alarm.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "eventbridge_dead_letter" {
  queue_url = aws_sqs_queue.alarm_dead_letter.id
  policy    = data.aws_iam_policy_document.eventbridge_dead_letter.json
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeAlarm"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm.arn
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name_prefix}-operations"
  dashboard_body = jsonencode({ widgets = [
    { type = "metric", width = 16, height = 7, properties = { title = "Metric and anomaly band", region = var.aws_region, stat = "Average", period = 60, metrics = [[var.metric_namespace, var.metric_name, "Service", var.service_dimension, { id = "m1", label = var.metric_name }], [{ expression = "ANOMALY_DETECTION_BAND(m1, ${var.anomaly_band_width})", id = "ad1", label = "Expected band" }]] } },
    { type = "alarm", width = 8, height = 7, properties = { title = "Alarm state", alarms = [aws_cloudwatch_metric_alarm.anomaly.arn] } }
  ] })
}
