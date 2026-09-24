output "metric_publisher_function" { value = aws_lambda_function.publisher.function_name }
output "alarm_router_function" { value = aws_lambda_function.router.function_name }
output "alert_topic_arn" { value = aws_sns_topic.alerts.arn }
output "alarm_name" { value = aws_cloudwatch_metric_alarm.anomaly.alarm_name }
output "dashboard_name" { value = aws_cloudwatch_dashboard.operations.dashboard_name }
output "eventbridge_dead_letter_queue_arn" { value = aws_sqs_queue.alarm_dead_letter.arn }
