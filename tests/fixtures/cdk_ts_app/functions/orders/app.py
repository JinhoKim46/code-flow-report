import os

import boto3


def create_order(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    table.put_item(Item={"id": event["id"]})
    boto3.client("sqs").send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event["id"])
    return {"statusCode": 201}
