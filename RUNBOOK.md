# Anomaly Detection Operations Runbook

## Service objectives

Recommended production objectives for this reference implementation:

- At least 99.9% of valid metric-publisher invocations succeed each month.
- At least 99% of CloudWatch `ALARM` transitions reach SNS within two minutes.
- No EventBridge delivery remains in the dead-letter queue for more than one business day.

Track these objectives with Lambda `Errors`, `Throttles`, and `Duration`; EventBridge `FailedInvocations` and `InvocationsSentToDLQ`; SNS delivery metrics; and SQS queue depth and message age.

## Signal contract

- The publisher accepts one validated standard-resolution custom metric per invocation.
- The alarm evaluates two consecutive one-minute periods against a learned CloudWatch band.
- Missing data is treated as non-breaching to avoid false incidents when a workload intentionally stops.
- EventBridge invokes the router only when the configured alarm enters `ALARM`.
- SNS fans out the normalized message to confirmed subscribers or an integration bridge.

## Alarm triage

1. Open the CloudWatch dashboard from the Terraform output and verify whether the value is above or below the learned band.
2. Confirm the namespace, metric, unit, and dimensions match the affected workload.
3. Compare deployments, traffic, dependencies, and scheduled jobs around the alarm timestamp.
4. Inspect publisher and router Lambda `Errors`, `Throttles`, and `Duration` metrics and their log groups.
5. Check EventBridge failed invocations and the dead-letter queue before concluding that downstream notification succeeded.
6. If the metric represents customer impact, follow the owning service's incident procedure and assign an incident commander.

## Missing notifications

1. Confirm the CloudWatch alarm entered `ALARM` and matched the EventBridge rule.
2. Check router Lambda logs for malformed events, missing configuration, throttling, or SNS failures.
3. Verify the SNS subscription is confirmed and inspect delivery status for the destination.
4. Inspect `ApproximateNumberOfMessagesVisible` and `ApproximateAgeOfOldestMessage` on the dead-letter queue.
5. After correcting the cause, replay a reviewed dead-letter event to the router Lambda and verify its SNS message ID.

Never copy credentials or vendor tokens into logs, Terraform variables, or dead-letter messages.

## False positives or missed anomalies

Compare the training period with traffic seasonality, deployments, and scheduled jobs. Adjust `anomaly_band_width` one step at a time and record the before-and-after alert volume. Confirm that the metric unit and dimensions have not changed. Do not silence the alarm until the signal and customer impact are understood.

The local simulator uses a rolling population standard deviation with a minimum 1% band. It deliberately excludes detected outliers from the learned baseline. Use it for workflow demonstrations and handler testing, not as a substitute for production forecasting.

## Recovery verification

Recovery is complete when:

- The metric remains inside the expected band for two evaluation periods.
- The CloudWatch alarm returns to `OK`.
- Lambda error and throttle rates are normal.
- EventBridge has no new failed deliveries and the dead-letter queue is empty.
- A confirmed downstream subscriber receives a controlled test alert.

Record the anomalous interval, impact, cause, mitigation, tuning changes, and follow-up owner.

## Rollback and cleanup

Use version control to revert Terraform changes, inspect `terraform plan`, and apply only the reviewed rollback. For a temporary notification stop, disable the EventBridge rule through a reviewed Terraform change and keep metric ingestion active for evidence. Destroy sandbox resources when testing is complete with `terraform destroy` after reviewing the resource plan.

