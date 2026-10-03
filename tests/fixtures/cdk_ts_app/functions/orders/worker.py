def handle(event, context):
    return [record["body"] for record in event["Records"]]
