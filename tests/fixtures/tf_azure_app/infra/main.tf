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
