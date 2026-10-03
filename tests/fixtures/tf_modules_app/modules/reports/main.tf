resource "aws_iam_role" "lambda" {
  name = "reports-lambda"
}

resource "aws_lambda_function" "nightly" {
  function_name = "nightly"
  filename      = var.archive_path
  handler       = "nightly.handler"
  role          = aws_iam_role.lambda.arn
}
