variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type        = string
  default     = "anomaly-poc"
  description = "Prefix for project resources."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.name_prefix))
    error_message = "name_prefix must be 3 to 32 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "metric_namespace" {
  type    = string
  default = "Portfolio/Operations"
  validation {
    condition     = length(var.metric_namespace) >= 1 && length(var.metric_namespace) <= 255 && !startswith(var.metric_namespace, "AWS/")
    error_message = "metric_namespace must be 1 to 255 characters and cannot use the reserved AWS/ prefix."
  }
}

variable "metric_name" {
  type    = string
  default = "PipelineLatency"
}

variable "metric_unit" {
  type    = string
  default = "Milliseconds"
}

variable "service_dimension" {
  type    = string
  default = "orders"
}
variable "anomaly_band_width" {
  type        = number
  default     = 2
  description = "Number of standard deviations used by the anomaly band."
  validation {
    condition     = var.anomaly_band_width >= 1 && var.anomaly_band_width <= 5
    error_message = "anomaly_band_width must be between 1 and 5."
  }
}
variable "notification_email" {
  type        = string
  default     = ""
  description = "Optional email address. SNS confirmation is required."
}
