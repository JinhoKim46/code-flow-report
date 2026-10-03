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
