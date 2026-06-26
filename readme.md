# langgraph-checkpoint-cosmosdb

Azure CosmosDB checkpoint saver for [LangGraph](https://github.com/langchain-ai/langgraph). Persists agent state between runs so your graphs can resume from any prior checkpoint.

## Features

- **Full checkpoint persistence** — save, retrieve, and list LangGraph checkpoints in CosmosDB
- **Sync and async API** — `put`/`get_tuple`/`list` and their `aput`/`aget_tuple`/`alist` async counterparts
- **Subgraph support** — correctly checkpoints parent and subgraph state independently
- **Flexible authentication** — key-based or Azure RBAC (Managed Identity, `az login`, service principal)
- **Auto-creates database and container** — when using key-based auth
- **Optional message pruning** — integrate with [`agentstate-reducer`](https://pypi.org/project/agentstate-reducer/) to cap message history size before persisting

## Installation

```bash
pip install langgraph-checkpoint-cosmosdb
```

With optional message pruning support:

```bash
pip install "langgraph-checkpoint-cosmosdb[reducer]"
```

**Requires Python 3.10+**

## Authentication

### Key-based (recommended for development)

Set both env vars — the saver will create the database and container if they don't exist:

```bash
export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
export COSMOSDB_KEY="<your-key>"
```

### Azure RBAC / Managed Identity (recommended for production)

Set only the endpoint — no key. The saver uses `DefaultAzureCredential`, which resolves in this order: environment variables → managed identity → `az login`.

```bash
export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
# Key not set → falls back to DefaultAzureCredential
```

For user-assigned managed identity also set:

```bash
export AZURE_CLIENT_ID="<managed-identity-client-id>"
```

For service principal:

```bash
export AZURE_TENANT_ID="<tenant-id>"
export AZURE_CLIENT_ID="<client-id>"
export AZURE_CLIENT_SECRET="<client-secret>"
```

> **Note:** When using RBAC the database and container must already exist — the saver will not create them automatically.

## Quick Start

```python
from langgraph.graph import StateGraph, MessagesState, START
from langchain_openai import ChatOpenAI
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

model = ChatOpenAI(model="gpt-4o-mini")

def call_model(state: MessagesState):
    return {"messages": model.invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model)
builder.add_edge(START, "call_model")

checkpointer = CosmosDBSaver(database_name="mydb", container_name="checkpoints")
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-123"}}

# First run — state is saved to CosmosDB
graph.invoke({"messages": [{"role": "user", "content": "Hi, I'm Kamal"}]}, config)

# Second run — picks up where it left off
graph.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

## API Reference

### `CosmosDBSaver(database_name, container_name, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `database_name` | `str` | required | CosmosDB database name |
| `container_name` | `str` | required | CosmosDB container name |
| `reducer` | `MessageReducer` | `None` | Optional pruner — see [Message Pruning](#message-pruning) |
| `messages_key` | `str` | `"messages"` | State channel name that holds the message list |

### Sync methods

| Method | Description |
|---|---|
| `put(config, checkpoint, metadata, new_versions)` | Save a checkpoint |
| `put_writes(config, writes, task_id)` | Save pending writes for a checkpoint |
| `get_tuple(config)` | Retrieve the latest (or a specific) checkpoint |
| `list(config, *, before, limit)` | Iterate checkpoints for a thread |

### Async methods

All sync methods have async counterparts: `aput`, `aput_writes`, `aget_tuple`, `alist`, and `adelete`.

```python
# Async usage
checkpoint = await saver.aget_tuple(config)
await saver.adelete(thread_id="user-123", checkpoint_namespace="", checkpoint_id="<id>")
```

### `list` usage

```python
# List all checkpoints for a thread (newest first)
for cp in saver.list(config={"configurable": {"thread_id": "user-123"}}):
    print(cp.checkpoint["id"], cp.metadata)

# Limit results
for cp in saver.list(config, limit=5):
    print(cp)
```

> **Limitation:** `list` only supports filtering by `thread_id`. The `filter` parameter (filtering by metadata) is not yet implemented.

## Subgraph Support

Works transparently with LangGraph subgraphs — parent and subgraph checkpoints are stored under the same container using namespaced partition keys:

```python
from langgraph.graph import StateGraph, START
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from typing import TypedDict

class SubState(TypedDict):
    foo: str
    bar: str

class State(TypedDict):
    foo: str

# ... build parent + subgraph as normal ...
checkpointer = CosmosDBSaver(database_name="mydb", container_name="checkpoints")
graph = parent_builder.compile(checkpointer=checkpointer)

for _, chunk in graph.stream({"foo": "hello"}, config, subgraphs=True):
    print(chunk)
```

## Message Pruning

For long-running agents, message history grows unboundedly. Use `agentstate-reducer` to cap the number of messages stored in each checkpoint:

```bash
pip install "langgraph-checkpoint-cosmosdb[reducer]"
```

```python
from agentstate_reducer import MessageReducer
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

checkpointer = CosmosDBSaver(
    database_name="mydb",
    container_name="checkpoints",
    reducer=reducer,        # prune before each save
    messages_key="messages" # name of the state channel (default)
)
```

The reducer runs transparently inside `put()` — the graph sees no difference. When the message list in the checkpoint exceeds `max_messages`, the oldest `human`/`ai` messages are pruned until `min_messages` remain. System messages, tool messages, and index 0 are always preserved.

See [agentstate-reducer docs](https://pypi.org/project/agentstate-reducer/) for full configuration options including summarization callbacks.

## Data Model

Checkpoints and writes are stored as separate items in the same CosmosDB container, differentiated by a key prefix and partition key:

| Item type | Partition key format | Item id format |
|---|---|---|
| Checkpoint | `checkpoint$<thread_id>$<ns>$` | `checkpoint$<thread_id>$<ns>$<checkpoint_id>` |
| Pending write | `writes$<thread_id>$<ns>$<checkpoint_id>$` | `writes$<thread_id>$<ns>$<checkpoint_id>$<task_id>$<idx>` |

The container requires a partition key path of `/partition_key`.

## License

MIT
