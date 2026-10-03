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
