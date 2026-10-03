"""Writes the fixture repos under tests/fixtures/. Run once; the result is committed.

Every name, URL and value here is invented. Each fixture exercises one part of the extractor;
tests/test_extract.py states exactly what must come out of each.
"""
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent / "fixtures"

FIXTURES = {
    "flask_app": {
        "schema.sql": """
            -- invented schema
            CREATE TABLE IF NOT EXISTS orders (id serial PRIMARY KEY, customer_id int, total int);
            CREATE TABLE customers (id serial PRIMARY KEY, name text);
            CREATE OR REPLACE VIEW order_totals AS SELECT customer_id, sum(total) FROM orders GROUP BY 1;
        """,
        "app/__init__.py": '''
            """Shop web app."""
            from flask import Flask

            from app.views import bp


            def create_app():
                app = Flask(__name__)
                app.register_blueprint(bp, url_prefix="/shop")
                return app
        ''',
        "app/auth.py": '''
            def login_required(view):
                """Lets the view run only for a signed-in user."""
                return view
        ''',
        "app/db.py": '''
            import sqlite3


            def connect():
                return sqlite3.connect("shop.db")
        ''',
        "app/orders.py": '''
            """Order reads and writes."""
            import requests

            from app.db import connect

            TOTALS_SQL = "SELECT customer_id FROM order_totals"


            def run_write(action, payload, work):
                """Every write goes through here."""
                with connect() as conn:
                    return work(conn.cursor())


            def list_orders(cur):
                return cur.execute("SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id").fetchall()


            def insert_order(cur, form):
                cur.execute("INSERT INTO orders (customer_id, total) VALUES (%s, %s)", (form["customer"], form["total"]))
                notify(form)


            def notify(form):
                requests.post("https://hooks.example.invalid/orders", json=form)


            def totals(cur):
                return cur.execute(TOTALS_SQL).fetchall()


            def unused_helper():
                return 1
        ''',
        "app/views.py": '''
            from flask import Blueprint, render_template, request

            from app import orders
            from app.auth import login_required
            from app.db import connect

            bp = Blueprint("shop", __name__)


            @bp.get("/orders")
            @login_required
            def list_orders():
                with connect() as conn:
                    rows = orders.list_orders(conn.cursor())
                return render_template("orders.html", rows=rows)


            @bp.route("/orders", methods=["POST"])
            @login_required
            def create_order():
                def work(cur):
                    orders.insert_order(cur, request.form)
                return orders.run_write("order_create", dict(request.form), work)
        ''',
        "tests/test_views.py": '''
            from app.orders import totals


            def test_totals():
                assert totals is not None
        ''',
    },
    "fastapi_llm": {
        "svc/__init__.py": "",
        "svc/main.py": '''
            from fastapi import FastAPI

            from svc import admin
            from svc.routes import router

            app = FastAPI()
            app.include_router(router, prefix="/api")
            app.include_router(admin.router, prefix="/api")
        ''',
        "svc/admin.py": '''
            from fastapi import APIRouter

            router = APIRouter(prefix="/admin")


            @router.get("/stats")
            def stats():
                return {}
        ''',
        "svc/routes.py": '''
            from fastapi import APIRouter

            from svc.agent import answer

            router = APIRouter(prefix="/v1")


            @router.post("/ask")
            def ask(question: str):
                """Answers one question."""
                return {"answer": answer(question)}
        ''',
        "svc/agent.py": '''
            from anthropic import Anthropic
            from pydantic import BaseModel

            MODEL = "demo-model-1"
            client = Anthropic()


            class Answer(BaseModel):
                text: str


            def answer(question):
                msg = client.messages.create(
                    model=MODEL,
                    max_tokens=512,
                    temperature=0.2,
                    system="You answer briefly.",
                    messages=[{"role": "user", "content": question}],
                    output_format=Answer,
                )
                return msg.content
        ''',
    },
    "django_site": {
        "shop/__init__.py": "",
        "shop/models.py": '''
            from django.db import models


            class Order(models.Model):
                total = models.IntegerField()


            class Invoice(models.Model):
                class Meta:
                    db_table = "billing_invoice"
        ''',
        "shop/views.py": '''
            from django.views import View

            from shop.models import Order


            def order_list(request):
                return list(Order.objects.all())


            class OrderDetail(View):
                def get(self, request, pk):
                    return Order.objects.get(pk=pk)
        ''',
        "shop/urls.py": '''
            from django.urls import path

            from shop import views

            urlpatterns = [
                path("orders/", views.order_list),
                path("orders/<int:pk>/", views.OrderDetail.as_view()),
            ]
        ''',
    },
    "celery_jobs": {
        "jobs/__init__.py": "",
        "jobs/tasks.py": '''
            from celery import shared_task

            from jobs.mail import send_digest


            @shared_task
            def nightly_digest():
                """Mails yesterday's summary."""
                send_digest()
        ''',
        "jobs/mail.py": '''
            import smtplib


            def send_digest():
                smtplib.SMTP("localhost").sendmail("from@example.invalid", ["to@example.invalid"], "summary")
        ''',
        "jobs/api.py": '''
            from jobs.tasks import nightly_digest


            def trigger():
                nightly_digest.delay()
        ''',
    },
    "src_layout_lib": {
        "src/pkg/__init__.py": '''
            """A tiny library."""
            from .core import run
        ''',
        "src/pkg/core.py": '''
            from . import util


            class Engine:
                def start(self):
                    return self.step()

                def step(self):
                    return util.helper(1)


            def run(x):
                return Engine().start() + util.helper(x)
        ''',
        "src/pkg/util.py": '''
            def helper(x):
                from pkg.core import run  # lazy on purpose: avoids a module-level cycle
                return x if x else run
        ''',
        "src/pkg/a.py": '''
            from pkg import b


            def fa():
                return b.fb()
        ''',
        "src/pkg/b.py": '''
            from pkg import a


            def fb():
                return a.fa
        ''',
        "src/pkg/cli.py": '''
            from pkg import run


            def main():
                run(1)


            if __name__ == "__main__":
                main()
        ''',
    },
    "oo_lib": {
        "oo/__init__.py": "",
        "oo/base.py": '''
            import argparse


            class Parser(argparse.ArgumentParser):
                """A library subclass: its inherited methods live in argparse."""


            class Store:
                def save(self):
                    return 1
        ''',
        "oo/app.py": '''
            import argparse

            from oo.base import Parser, Store

            parser = Parser()
            parser.add_argument("--verbose")


            class Service:
                def __init__(self):
                    self.store = Store()

                def run(self):
                    return self.store.save()


            def configure(p: argparse.ArgumentParser):
                p.add_argument("--quiet")
        ''',
        "oo/use.py": '''
            from oo.app import parser


            def main():
                return parser.parse_args()
        ''',
        "oo/models.py": '''
            from sqlmodel import SQLModel


            class Hero(SQLModel, table=True):
                id: int
        ''',
    },
    "types_lib": {
        "tl/__init__.py": "",
        "tl/store.py": '''
            from dataclasses import dataclass
            from typing import Optional


            class Store:
                def save(self):
                    return 1

                def only_here_xyz(self):
                    return 2


            class Child(Store):
                def save(self):
                    return super().save()


            @dataclass
            class Box:
                store: Store


            def make() -> Store:
                return Store()


            def build():
                return Store()


            def maybe(s: Optional[Store]):
                return s.save()


            def quoted(s: "Store"):
                return s.save()
        ''',
        "tl/use.py": '''
            import csv

            from tl.store import Box, Store, build, make


            def returns():
                a = make()
                b = build()
                return a.save() + b.save()


            def field(box: Box):
                return box.store.save()


            def takes(x):
                return x.save()


            def caller():
                return takes(Store())


            def values(data=None):
                d = data or {}
                return d.get("k"), ", ".join(["a", "b"]), "x".upper().strip()


            def rows(f):
                for row in csv.reader(f):
                    row.count("a")


            def guess(obj):
                return obj.only_here_xyz()
        ''',
    },
    "broken": {
        "good.py": '''
            def ok():
                return 1
        ''',
        "bad.py": '''
            def broken(:
                pass
        ''',
    },
    "llm_app": {
        "src/ai/__init__.py": "",
        "src/ai/adapters/__init__.py": "",
        "src/ai/adapters/openai.py": "def adapt(text):\n    return text\n",  # must not shadow the openai package
        "src/ai/client.py": """
            from openai import OpenAI


            class LLMClient:
                def __init__(self, sdk: OpenAI | None = None):
                    self.sdk = sdk or OpenAI()

                def chat(self, role: str, messages: list, model: str | None = None) -> str:
                    return self.sdk.chat.completions.create(model=model, messages=messages)

                def chat_json(self, role: str, messages: list, schema, model: str | None = None):
                    return schema.model_validate_json(self.chat(role, messages, model=model))
        """,
        "src/ai/deps.py": """
            from dataclasses import dataclass
            from typing import Callable

            from ai.client import LLMClient


            @dataclass
            class Deps:
                make_llm: Callable[[int], LLMClient]
        """,
        "src/ai/wiring.py": """
            from ai.client import LLMClient
            from ai.deps import Deps


            def build_deps() -> Deps:
                def make_llm(user_id: int) -> LLMClient:
                    return LLMClient()

                return Deps(make_llm=make_llm)
        """,
        "src/ai/judge.py": """
            from pydantic import BaseModel

            from ai.deps import Deps


            class Verdict(BaseModel):
                score: int


            def judge_messages(text: str) -> list:
                return [{"role": "user", "content": text}]


            def run_judge(deps: Deps, text: str) -> Verdict:
                llm = deps.make_llm(1)
                return llm.chat_json("judge", judge_messages(text), Verdict, model="demo-judge", temperature=0)
        """,
        "src/ai/guard.py": """
            from ai.client import LLMClient


            class Guard:
                def __init__(self, llm: LLMClient | None = None):
                    self.llm = llm

                def check(self, text: str) -> str:
                    return self.llm.chat("guard", [{"role": "user", "content": text}])
        """,
        "src/ai/decide.py": """
            import httpx


            def decide(payload: dict) -> dict:
                return httpx.post("https://openrouter.ai/api/v1/decisions", json=payload).json()
        """,
        "scripts/helpers.py": """
            def ping() -> str:
                return "pong"
        """,
        "scripts/run.py": """
            import helpers


            def main():
                return helpers.ping()


            if __name__ == "__main__":
                main()
        """,
    },
    "lib_pkg": {
        "pyproject.toml": """
            [project]
            name = "lib"
            version = "0.1.0"

            [project.scripts]
            libtool = "lib.cli:run"
        """,
        "schema/0001.surql": """
            DEFINE TABLE IF NOT EXISTS note SCHEMAFULL;
        """,
        "src/lib/__init__.py": "from .chain import ask\n",
        "src/lib/models.py": """
            from openai import OpenAI


            class Model:
                def generate(self, messages):
                    raise NotImplementedError


            class ApiModel(Model):
                pass


            class OpenAIModel(ApiModel):
                def __init__(self):
                    self.client = OpenAI()

                def generate(self, messages):
                    return self.retry(self.client.chat.completions.create, messages=messages)

                def retry(self, fn, **kwargs):
                    return fn(**kwargs)
        """,
        "src/lib/agents.py": """
            from lib.models import Model

            __all__ = ["Agent"]


            class Base:
                def __init__(self, model: Model):
                    self.model = model

                def run(self, task):
                    return self.step(task)

                def step(self, task):
                    raise NotImplementedError


            class Agent(Base):
                def step(self, task):
                    return self.model.generate([task])
        """,
        "src/lib/store.py": """
            from typing import ClassVar


            class Record:
                table_name: ClassVar[str] = ""

                def save(self):
                    return self

                @classmethod
                def get_all(cls):
                    return []


            class Note(Record):
                table_name: ClassVar[str] = "note"


            def add_note(text: str) -> Note:
                note = Note()
                note.save()
                return note


            def list_notes():
                return Note.get_all()
        """,
        "src/lib/chain.py": """
            from langchain_core.messages import HumanMessage


            def ask(llm, question: str):
                return llm.invoke([HumanMessage(content=question)])
        """,
        "src/lib/cli.py": """
            from lib.store import add_note, list_notes


            def run():
                add_note("hello")
                return list_notes()
        """,
        "scripts/seed.py": """
            from lib.store import add_note, list_notes

            add_note("one")
            add_note("two")
            print(list_notes())
        """,
    },
    "cdk_ts_app": {
        "cdk.json": '{"app": "npx ts-node bin/app.ts"}\n',
        "lib/storage.ts": """
            import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
            import { Construct } from "constructs";

            export class Storage extends Construct {
              public readonly ordersTable: dynamodb.Table;

              constructor(scope: Construct, id: string) {
                super(scope, id);
                const table = new dynamodb.Table(this, "Orders", {
                  partitionKey: { name: "id", type: dynamodb.AttributeType.STRING },
                });
                this.ordersTable = table;
              }
            }
        """,
        "lib/app-stack.ts": """
            import * as cdk from "aws-cdk-lib";
            import * as lambda from "aws-cdk-lib/aws-lambda";
            import * as sqs from "aws-cdk-lib/aws-sqs";
            import * as apigw from "aws-cdk-lib/aws-apigateway";
            import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
            import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
            import { Construct } from "constructs";
            import * as path from "path";
            import { Storage } from "./storage";

            export class AppStack extends cdk.Stack {
              constructor(scope: Construct, id: string, props?: cdk.StackProps) {
                super(scope, id, props);
                const storage = new Storage(this, "Storage");
                const queue = new sqs.Queue(this, "OrdersQueue");
                // a comment such as new lambda.Function(this, "Fake", {}) is not a resource
                const api = new apigw.RestApi(this, "Api");
                const createOrder = new lambda.Function(this, "CreateOrder", {
                  runtime: lambda.Runtime.PYTHON_3_12,
                  handler: "app.create_order",
                  code: lambda.Code.fromAsset(path.join(__dirname, "../functions/orders")),
                  environment: {
                    TABLE_NAME: storage.ordersTable.tableName,
                    QUEUE_URL: queue.queueUrl,
                  },
                });
                const worker = new LambdaFunction(this, "Worker", {
                  runtime: lambda.Runtime.PYTHON_3_12,
                  handler: "worker.handle",
                  code: lambda.Code.fromAsset("functions/orders"),
                });
                const orders = api.root.addResource("orders");
                orders.addMethod("POST", new apigw.LambdaIntegration(createOrder));
                worker.addEventSource(new SqsEventSource(queue));
                storage.ordersTable.grantReadWriteData(createOrder);
                queue.grantSendMessages(createOrder);
                allowRead(worker);

                function allowRead(fn: lambda.Function) {
                  storage.ordersTable.grantReadData(fn);
                }
              }
            }
        """,
        "functions/orders/app.py": """
            import os

            import boto3


            def create_order(event, context):
                table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
                table.put_item(Item={"id": event["id"]})
                boto3.client("sqs").send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event["id"])
                return {"statusCode": 201}
        """,
        "functions/orders/worker.py": """
            def handle(event, context):
                return [record["body"] for record in event["Records"]]
        """,
    },
    "cdk_py_app": {
        "cdk.json": '{"app": "python3 app.py"}\n',
        "infra/stack.py": """
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
        """,
        "functions/ingest.py": """
            def handler(event, context):
                return len(event["Records"])
        """,
    },
    "tf_aws_app": {
        "infra/main.tf": """
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
        """,
        "jobs/Dockerfile": """
            FROM public.ecr.aws/lambda/python:3.12
            COPY ./jobs/handler.py .
            CMD ["handler.run"]
        """,
        "jobs/handler.py": """
            def run(event, context):
                return "done"
        """,
        "src/orders/app.py": """
            import os

            import boto3


            def create_order(event, context):
                boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]).put_item(Item={"id": event["id"]})
                return {"statusCode": 201}
        """,
        "src/orders/worker.py": """
            def handle(event, context):
                return len(event.get("Records", []))
        """,
    },
    "tf_gcp_app": {
        "terraform/main.tf": """
            data "archive_file" "src" {
              type        = "zip"
              source_dir  = "${path.module}/../function"
              output_path = "/tmp/function.zip"
            }

            resource "google_storage_bucket" "source" {
              name     = "src-bucket"
              location = "US"
            }

            resource "google_storage_bucket_object" "zip" {
              name   = "function.zip"
              bucket = google_storage_bucket.source.name
              source = data.archive_file.src.output_path
            }

            resource "google_pubsub_topic" "jobs" {
              name = "jobs"
            }

            resource "google_service_account" "fn" {
              account_id = "fn-sa"
            }

            resource "google_cloudfunctions2_function" "process" {
              name = "process"
              build_config {
                runtime     = "python312"
                entry_point = "process_job"
                source {
                  storage_source {
                    bucket = google_storage_bucket.source.name
                    object = google_storage_bucket_object.zip.name
                  }
                }
              }
              service_config {
                service_account_email = google_service_account.fn.email
                environment_variables = {
                  OUTPUT_BUCKET = google_storage_bucket.source.name
                }
              }
              event_trigger {
                event_type   = "google.cloud.pubsub.topic.v1.messagePublished"
                pubsub_topic = google_pubsub_topic.jobs.id
              }
            }

            resource "google_cloudfunctions_function" "api" {
              name                  = "api"
              runtime               = "python311"
              entry_point           = "handle_http"
              trigger_http          = true
              source_archive_bucket = google_storage_bucket.source.name
              source_archive_object = google_storage_bucket_object.zip.name
            }

            resource "google_cloud_scheduler_job" "hourly" {
              name     = "hourly"
              schedule = "0 * * * *"
              pubsub_target {
                topic_name = google_pubsub_topic.jobs.id
                data       = base64encode("go")
              }
            }

            resource "google_storage_bucket_iam_member" "writer" {
              bucket = google_storage_bucket.source.name
              role   = "roles/storage.objectAdmin"
              member = "serviceAccount:${google_service_account.fn.email}"
            }
        """,
        "function/main.py": """
            def process_job(event, context):
                return event


            def handle_http(request):
                return "ok"
        """,
    },
    "tf_azure_app": {
        "infra/main.tf": """
            resource "azurerm_storage_account" "main" {
              name                     = "ordersstore"
              account_tier             = "Standard"
              account_replication_type = "LRS"
            }

            resource "azurerm_storage_queue" "jobs" {
              name                 = "jobs"
              storage_account_name = azurerm_storage_account.main.name
            }

            resource "azurerm_cosmosdb_account" "db" {
              name = "orders-db"
            }

            resource "azurerm_linux_function_app" "api" {
              name                       = "orders-api"
              storage_account_name       = azurerm_storage_account.main.name
              app_settings = {
                COSMOS_ENDPOINT = azurerm_cosmosdb_account.db.endpoint
                JOBS_QUEUE      = azurerm_storage_queue.jobs.name
              }
              identity {
                type = "SystemAssigned"
              }
            }

            resource "azurerm_role_assignment" "cosmos" {
              scope                = azurerm_cosmosdb_account.db.id
              role_definition_name = "Cosmos DB Built-in Data Contributor"
              principal_id         = azurerm_linux_function_app.api.identity[0].principal_id
            }
        """,
        "app/function_app.py": """
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
        """,
    },
    "tf_modules_app": {
        "main.tf": """
            module "packaging" {
              source = "./modules/archives"
            }

            module "intake" {
              source       = "./modules/intake"
              archive_path = module.packaging.intake_archive_path
            }

            module "reports" {
              source       = "./modules/reports"
              archive_path = module.packaging.reports_archive_path
            }
        """,
        "modules/archives/main.tf": """
            locals {
              src = "${path.module}/../../src"
            }

            resource "archive_file" "intake" {
              type        = "zip"
              source_dir  = "${local.src}/intake"
              output_path = "${local.src}/intake.zip"
            }

            resource "archive_file" "reports" {
              type        = "zip"
              source_dir  = "${local.src}/reports"
              output_path = "${local.src}/reports.zip"
            }
        """,
        "modules/archives/outputs.tf": """
            output "intake_archive_path" {
              value = archive_file.intake.output_path
            }

            output "reports_archive_path" {
              value = archive_file.reports.output_path
            }
        """,
        "modules/intake/variables.tf": """
            variable "archive_path" {
              type = string
            }
        """,
        "modules/intake/main.tf": """
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
        """,
        "modules/intake/policy.tpl": """
            {
              "Version": "2012-10-17",
              "Statement": [
                {"Effect": "Allow", "Action": ["dynamodb:PutItem"], "Resource": "${table_arn}"}
              ]
            }
        """,
        "modules/intake/states.json": """
            {
              "StartAt": "Validate",
              "States": {
                "Validate": {"Type": "Task", "Resource": "${validate_arn}", "Next": "Store"},
                "Store": {"Type": "Task", "Resource": "${ store_arn }", "End": true}
              }
            }
        """,
        "modules/reports/variables.tf": """
            variable "archive_path" {
              type = string
            }
        """,
        "modules/reports/main.tf": """
            resource "aws_iam_role" "lambda" {
              name = "reports-lambda"
            }

            resource "aws_lambda_function" "nightly" {
              function_name = "nightly"
              filename      = var.archive_path
              handler       = "nightly.handler"
              role          = aws_iam_role.lambda.arn
            }
        """,
        "src/intake/validate.py": """
            def handler(event, context):
                return event
        """,
        "src/intake/store.py": """
            def handler(event, context):
                return "stored"
        """,
        "src/reports/nightly.py": """
            def handler(event, context):
                return "report"
        """,
    },
    "compose_app": {
        "compose.yaml": """
            x-env: &common-env
              LOG_LEVEL: info

            services:
              api:
                build:
                  context: ./backend
                ports:
                  - "8000:8000"
                environment:
                  <<: *common-env
                  DATABASE_URL: postgresql://app:${DB_PASSWORD:-changeme}@db:5432/app
                  REDIS_URL: redis://cache:6379/0
                depends_on:
                  db:
                    condition: service_healthy
                  cache:
                    condition: service_started

              worker:
                build: ./backend
                command: celery -A app.worker worker --loglevel=info
                environment:
                  - REDIS_URL=redis://cache:6379/0
                depends_on: [cache]

              ingest:
                build: ./backend
                command: ["python", "-m", "app.jobs.ingest"]
                depends_on:
                  - db

              db:
                image: postgres:16
                volumes:
                  - pgdata:/var/lib/postgresql/data

              cache:
                image: redis:7-alpine

              allinone:
                image: example/compose_app:latest
                depends_on: [db]

            volumes:
              pgdata:
        """,
        "Dockerfile": """
            FROM python:3.12-slim AS base
            WORKDIR /app
            COPY backend/ .
            COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
            CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

            FROM base AS runtime
            ENV MODE=prod
        """,
        "supervisord.conf": """
            [supervisord]
            nodaemon=true

            [program:api]
            command=uv run --no-sync uvicorn app.main:app --port %(ENV_PORT)s

            [program:worker]
            command=sh -c "celery -A app.worker worker"

            [program:web]
            command=node server.js
        """,
        "examples/compose.yaml": """
            services:
              demo:
                build: ../backend
        """,
        "compose.override.yaml": """
            services:
              api:
                command: uvicorn app.main:app --host 0.0.0.0 --reload
        """,
        "backend/Dockerfile": """
            FROM python:3.12-slim
            WORKDIR /app
            COPY . .
            CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app"]
        """,
        "backend/app/__init__.py": "",
        "backend/app/main.py": """
            from fastapi import FastAPI

            app = FastAPI()


            @app.get("/health")
            def health():
                return {"ok": True}
        """,
        "backend/app/worker.py": """
            from celery import Celery

            celery = Celery("app")


            @celery.task
            def reindex(doc_id):
                return doc_id
        """,
        "backend/app/jobs/__init__.py": "",
        "backend/app/jobs/ingest.py": """
            def load():
                return []


            load()
        """,
    },
    "k8s_app": {
        "deploy/app.yaml": """
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: api
            spec:
              selector:
                matchLabels: {app: api}
              template:
                metadata:
                  labels:
                    app: api
                spec:
                  containers:
                    - name: api
                      image: ghcr.io/example/api:1.4.0
                      env:
                        - name: DB_HOST
                          value: postgres
                        - name: FEATURE_FLAGS
                          valueFrom:
                            configMapKeyRef:
                              name: settings
                              key: flags
                      envFrom:
                        - secretRef:
                            name: api-secrets
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: api
            spec:
              selector:
                app: api
              ports:
                - port: 80
                  targetPort: 8000
            ---
            apiVersion: networking.k8s.io/v1
            kind: Ingress
            metadata:
              name: public
            spec:
              rules:
                - host: example.com
                  http:
                    paths:
                      - path: /v1
                        pathType: Prefix
                        backend:
                          service:
                            name: api
                            port:
                              number: 80
            ---
            apiVersion: batch/v1
            kind: CronJob
            metadata:
              name: nightly-report
            spec:
              schedule: "0 3 * * *"
              jobTemplate:
                spec:
                  template:
                    spec:
                      containers:
                        - name: report
                          image: ghcr.io/example/api:1.4.0
                          command: ["python", "-m", "api.jobs.report"]
                      volumes:
                        - name: out
                          persistentVolumeClaim:
                            claimName: reports
            ---
            apiVersion: v1
            kind: ConfigMap
            metadata:
              name: settings
            data:
              flags: "beta"
            ---
            apiVersion: v1
            kind: Secret
            metadata:
              name: api-secrets
            ---
            apiVersion: v1
            kind: PersistentVolumeClaim
            metadata:
              name: reports
            ---
            apiVersion: apps/v1
            kind: StatefulSet
            metadata:
              name: postgres
            spec:
              template:
                metadata:
                  labels: {app: postgres}
                spec:
                  containers:
                    - name: postgres
                      image: postgres:16
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: postgres
            spec:
              selector: {app: postgres}
              ports: [{port: 5432}]
            ---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: report-cli
            spec:
              template:
                spec:
                  containers:
                    - name: cli
                      image: ghcr.io/example/api:1.4.0
                      command: ["report-cli", "--daily"]
            ---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: sidecar-cache
            spec:
              template:
                spec:
                  containers:
                    - name: cache
                      image: ghcr.io/example/api:1.4.0
                      command: ["/opt/bin/cache-server", "0.0.0.0", "8000"]
        """,
        "pyproject.toml": """
            [project]
            name = "example"
            version = "0.1.0"

            [project.scripts]
            report-cli = "api.jobs.report:build"
        """,
        "api/Dockerfile": """
            FROM python:3.12-slim
            WORKDIR /srv
            COPY . .
            ENTRYPOINT ["./entrypoint.sh"]
        """,
        "api/entrypoint.sh": """
            #!/bin/sh
            set -e
            python -m api.migrate
            exec gunicorn -b 0.0.0.0:8000 "api.wsgi:create_app()"
        """,
        "api/__init__.py": "",
        "api/migrate.py": """
            def run():
                return None
        """,
        "api/wsgi.py": """
            from flask import Flask


            def create_app():
                return Flask(__name__)
        """,
        "api/jobs/__init__.py": "",
        "api/jobs/report.py": """
            def build():
                return "report"


            build()
        """,
        "charts/web/Chart.yaml": """
            apiVersion: v2
            name: web
            version: 0.1.0
        """,
        "charts/web/values.yaml": """
            image:
              repository: ghcr.io/example/web
            command: ["streamlit", "run", "ui/app.py"]
        """,
        "charts/web/templates/engines.yaml": """
            {{- range $spec := .Values.engines }}
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: "{{ .Release.Name }}-{{ $spec.name }}-engine"
            spec:
              template:
                spec:
                  containers:
                    - name: engine
                      image: "vllm/vllm-openai:latest"
            ---
            {{- end }}
        """,
        "charts/web/templates/deployment.yaml": """
            {{- if .Values.enabled | default true }}
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: {{ include "web.fullname" . }}
              labels:
                {{- include "web.labels" . | nindent 4 }}
            spec:
              template:
                metadata:
                  labels:
                    app: web
                spec:
                  containers:
                    - name: web
                      image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default "latest" }}"
                      command: ["streamlit", "run", "ui/app.py"]
                      env:
                        - name: API_URL
                          value: "http://api/v1"
            {{- end }}
        """,
        "ui/app.py": """
            import streamlit as st

            st.title("web")
        """,
    },
    "streamlit_app": {
        "app/main.py": """
            import streamlit as st

            st.navigation([st.Page("views/notes.py", title="Notes")]).run()
        """,
        "app/views/notes.py": """
            import streamlit as st

            from notes.store import delete_note, save_note
            from notes.db import make_engine

            engine = make_engine()
            text = st.text_area("Note")
            if st.button("Save note"):
                save_note(engine, text)
                st.toast("Saved")


            def delete_form(note_id: int):
                if st.button("Delete"):
                    delete_note(engine, note_id)
        """,
        "src/notes/__init__.py": "",
        "src/notes/db.py": """
            from contextlib import contextmanager
            from typing import Iterator

            from pydantic import SecretStr
            from sqlmodel import Field, Session, SQLModel, create_engine


            class Note(SQLModel, table=True):
                id: int | None = Field(default=None, primary_key=True)
                text: str


            class Tag(SQLModel, table=True):
                id: int | None = Field(default=None, primary_key=True)
                note_id: int


            def make_engine(key: SecretStr | None = None):
                token = key.get_secret_value() if key else ""
                return create_engine("sqlite://", connect_args={"token": token})


            @contextmanager
            def session_scope(engine) -> Iterator[Session]:
                with Session(engine) as session:
                    yield session
                    session.commit()
        """,
        "src/notes/store.py": """
            from sqlmodel import select

            from notes.db import Note, Tag, session_scope


            def save_note(engine, text: str) -> None:
                with session_scope(engine) as s:
                    s.add(Note(text=text))


            def delete_note(engine, note_id: int) -> bool:
                with session_scope(engine) as s:
                    row = s.exec(select(Note).where(Note.id == note_id)).first()
                    tags = s.exec(select(Tag).where(Tag.note_id == note_id)).all()
                    if row is None:
                        return False
                    s.delete(row)
                    return bool(tags)
        """,
    },
}


def main():
    for name, files in FIXTURES.items():
        for rel, text in files.items():
            path = ROOT / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dedent(text).lstrip("\n"), encoding="utf-8")
    print("fixtures written:", ", ".join(FIXTURES))


if __name__ == "__main__":
    main()
