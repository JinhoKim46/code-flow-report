import os

import boto3


def create_order(event, context):
    boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]).put_item(Item={"id": event["id"]})
    return {"statusCode": 201}
