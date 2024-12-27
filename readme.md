# LangGraph Checkpoint CosmosDB

This project provides an implementation of a checkpoint saver for LangGraph using Azure CosmosDB. 

## Features
- Save and retrieve langgraph checkpoints in Azure CosmosDB.

## Installation

To install the package, ensure you have Python 3.9 or higher, and run:

```pip install langgraph-checkpoint-cosmosdb```

## Usage

### Setting Up Environment

To use the `CosmosDBSaver`
- You need to set CosmosDB endpoint and key if you want it to create your specified database and container.
```
export COSMOSDB_ENDPOINT='your_cosmosdb_endpoint'
export COSMOSDB_KEY='your_cosmosdb_key'
```
- If database and container already exists then this can work via default RBAC credentials. Ex. az login or by setting TENANT_ID, CLIENT_ID and CLIENT_SECRET in environment. 
    - Note that in this case error will be thrown if database and container do not exist.  


## Import

```
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
```

## Initialize the saver
Database and Container is created if it does not exists
```
saver = CosmosDBSaver(database_name='your_database', container_name='your_container')
```

## Limitations
List function does not support filters. You can only pass config on thread id to get the list.

```
print(list(memory.list(config=config)))
```
## License

This project is licensed under the MIT License.
