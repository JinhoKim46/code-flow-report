locals {
  src = "${path.module}/../src"
}

data "archive_file" "orders" {
  type        = "zip"
  source_dir  = "${local.src}/orders"
  output_path = "${path.module}/build/orders.zip"
}

resource "aws_dynamodb_table" "orders" {
  name     = "orders"
  hash_key = "id"
}

resource "aws_sqs_queue" "jobs" {
  name = "jobs"
}

resource "aws_iam_role" "fn" {
  name               = "orders-fn"
  assume_role_policy = jsonencode({ Version = "2012-10-17" })
}

resource "aws_iam_role_policy" "fn" {
  role = aws_iam_role.fn.id
  policy = jsonencode({
    Statement = [
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:GetItem"], Resource = [aws_dynamodb_table.orders.arn] },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [aws_sqs_queue.jobs.arn] },
    ]
  })
}

resource "aws_lambda_function" "create_order" {
  function_name = "create-order"
  role          = aws_iam_role.fn.arn
  handler       = "app.create_order"
  runtime       = "python3.12"
  filename      = data.archive_file.orders.output_path
  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.orders.name
      QUEUE_URL  = aws_sqs_queue.jobs.url
    }
  }
}

resource "aws_lambda_function" "worker" {
  function_name = "worker"
  role          = aws_iam_role.fn.arn
  handler       = "worker.handle"
  runtime       = "python3.12"
  filename      = data.archive_file.orders.output_path
}

# resource "aws_lambda_function" "commented" { handler = "x.y" }

resource "aws_lambda_event_source_mapping" "jobs" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.worker.arn
}

resource "aws_apigatewayv2_api" "http" {
  name          = "orders"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "create" {
  api_id           = aws_apigatewayv2_api.http.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.create_order.invoke_arn
}

resource "aws_apigatewayv2_route" "create" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /orders"
  target    = "integrations/${aws_apigatewayv2_integration.create.id}"
}

resource "aws_cloudwatch_event_rule" "nightly" {
  name                = "nightly"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "nightly" {
  rule = aws_cloudwatch_event_rule.nightly.name
  arn  = aws_lambda_function.worker.arn
}

resource "docker_image" "jobs" {
  name = "jobs:latest"
  build {
    context    = "${path.module}/.."
    dockerfile = "jobs/Dockerfile"
  }
}

resource "docker_registry_image" "jobs" {
  name = docker_image.jobs.name
}

resource "aws_lambda_function" "image_fn" {
  function_name = "image-fn"
  role          = aws_iam_role.fn.arn
  package_type  = "Image"
  image_uri     = docker_registry_image.jobs.name
}
