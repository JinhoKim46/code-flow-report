resource "aws_dynamodb_table" "requests" {
  name = "requests"
}

resource "aws_iam_role" "lambda" {
  name = "intake-lambda"
}

resource "aws_iam_role_policy" "lambda" {
  role   = aws_iam_role.lambda.id
  policy = templatefile("${path.module}/policy.tpl", {
    table_arn = aws_dynamodb_table.requests.arn
  })
}

resource "aws_lambda_function" "validate" {
  function_name = "validate"
  filename      = var.archive_path
  handler       = "validate.handler"
  role          = aws_iam_role.lambda.arn
}

resource "aws_lambda_function" "store" {
  function_name = "store"
  filename      = var.archive_path
  handler       = "store.handler"
  role          = aws_iam_role.lambda.arn
}

locals {
  replacements = {
    validate_arn = aws_lambda_function.validate.arn
    store_arn    = aws_lambda_function.store.arn
  }
}

resource "aws_sfn_state_machine" "intake" {
  name       = "intake"
  role_arn   = aws_iam_role.lambda.arn
  definition = templatefile("${path.module}/states.json", local.replacements)
}
