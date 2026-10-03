from aws_cdk import Stack
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from constructs import Construct


class IngestStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        bucket = s3.Bucket(self, "Uploads")
        fn = _lambda.Function(
            self, "Ingest",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="ingest.handler",
            code=_lambda.Code.from_asset("functions"),
            environment={"BUCKET": bucket.bucket_name},
        )
        bucket.grant_read(fn)
        bucket.add_event_notification(s3.EventType.OBJECT_CREATED, s3n.LambdaDestination(fn))
