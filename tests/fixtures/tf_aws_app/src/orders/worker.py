def handle(event, context):
    return len(event.get("Records", []))
