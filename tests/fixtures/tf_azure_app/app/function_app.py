import azure.functions as func

app = func.FunctionApp()


@app.route(route="orders", methods=["POST"])
def create_order(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("created", status_code=201)


@app.queue_trigger(arg_name="msg", queue_name="jobs", connection="AzureWebJobsStorage")
def process_job(msg: func.QueueMessage) -> None:
    print(msg.get_body())


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")
def sweep(timer: func.TimerRequest) -> None:
    return None
