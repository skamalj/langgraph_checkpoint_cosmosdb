# langgraph-checkpoint-cosmosdb

Azure CosmosDB checkpoint saver for [LangGraph](https://github.com/langchain-ai/langgraph). Persists agent state between runs so your graphs can resume from any prior checkpoint.

**What makes this checkpointer different:** it has message history pruning built in. Pass a `MessageReducer` and the checkpointer automatically caps your message list before writing to CosmosDB — no extra code in your graph, no state annotation changes required. This is the only LangGraph CosmosDB checkpointer with this capability.

## Features

- **Full checkpoint persistence** — save, retrieve, and list LangGraph checkpoints in CosmosDB
- **Built-in message pruning** — optional `MessageReducer` prunes message history at the persistence layer, keeping checkpoints lean without changing your graph code
- **Sync and async API** — `put`/`get_tuple`/`list` and their `aput`/`aget_tuple`/`alist` async counterparts
- **Subgraph support** — correctly checkpoints parent and subgraph state independently
- **Flexible authentication** — key-based or Azure RBAC (Managed Identity, `az login`, service principal)
- **Auto-creates database and container** — when using key-based auth

## Installation

```bash
pip install langgraph-checkpoint-cosmosdb
```

With optional message pruning support:

```bash
pip install "langgraph-checkpoint-cosmosdb[reducer]"
```

**Requires Python 3.10+**

## Database and Container Setup

| Auth mode | Database | Container | Partition key |
|---|---|---|---|
| **Key-based** (`COSMOSDB_KEY` set) | Created automatically if absent | Created automatically if absent | `/partition_key` (set by saver) |
| **RBAC / Managed Identity** (no key) | **Must pre-exist** | **Must pre-exist** | `/partition_key` (must be pre-configured) |

**Key-based** is the easiest way to get started — just point the saver at an existing CosmosDB account and it will provision everything.

**RBAC** is recommended for production. Because the saver only calls `get_database_client` / `get_container_client` (no write permissions needed at setup time), the database and container must already be provisioned before the saver is initialised. Create them via the Azure portal, Terraform, Bicep, or the Azure CLI:

```bash
az cosmosdb sql database create --account-name <account> --name <db>
az cosmosdb sql container create \
  --account-name <account> --database-name <db> --name <container> \
  --partition-key-path "/partition_key"
```

> **Important:** The partition key path must be `/partition_key` regardless of how the container is created.

## Authentication

### Key-based (development / admin access)

```bash
export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
export COSMOSDB_KEY="<your-key>"
```

### Azure RBAC / Managed Identity (production)

Set only the endpoint — no key. The saver uses `DefaultAzureCredential`, which resolves in this order: environment service principal → managed identity → `az login`.

```bash
export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
# COSMOSDB_KEY not set → DefaultAzureCredential is used
```

For **user-assigned managed identity**:

```bash
export AZURE_CLIENT_ID="<managed-identity-client-id>"
```

For **service principal**:

```bash
export AZURE_TENANT_ID="<tenant-id>"
export AZURE_CLIENT_ID="<client-id>"
export AZURE_CLIENT_SECRET="<client-secret>"
```

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

## Built-in Message Pruning

Long-running agents accumulate message history with every turn. Left unchecked this inflates checkpoint size, increases CosmosDB storage costs, and eventually blows past LLM context limits.

This checkpointer solves that at the persistence layer: pass a `MessageReducer` and it automatically prunes the message list inside `put()` before the checkpoint is serialised and written to CosmosDB. **Your graph code, state definition, and node logic stay untouched.**

This is an alternative to — or complement of — the LangGraph `Annotated[list, reducer_fn]` pattern. Use the checkpoint-layer approach when:

- You don't own the graph or state definition (e.g. using a pre-built LangGraph agent)
- You want pruning to happen unconditionally at every save, regardless of which node triggered it
- You want to keep all in-memory state intact and only prune what gets persisted

### Install with reducer support

```bash
pip install "langgraph-checkpoint-cosmosdb[reducer]"
```

### Usage

```python
from agentstate_reducer import MessageReducer
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

checkpointer = CosmosDBSaver(
    database_name="mydb",
    container_name="checkpoints",
    reducer=reducer,        # prune before each checkpoint save
    messages_key="messages" # state channel holding the message list (default)
)
```

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. The following are **never** pruned:

- Index 0 (typically the system prompt) — controlled by `preserve_first=True`
- `system` and `function` messages
- `tool` messages — unless their parent `ai` message is pruned (cascade behaviour, configurable)

See [agentstate-reducer on PyPI](https://pypi.org/project/agentstate-reducer/) for full configuration: `preserve_first`, `cascade_tool_messages`, `summarize_fn`, and role alias support (`user`/`assistant`/`agent`).

## Data Model

Checkpoints and writes are stored as separate items in the same CosmosDB container, differentiated by a key prefix and partition key:

| Item type | Partition key format | Item id format |
|---|---|---|
| Checkpoint | `checkpoint$<thread_id>$<ns>$` | `checkpoint$<thread_id>$<ns>$<checkpoint_id>` |
| Pending write | `writes$<thread_id>$<ns>$<checkpoint_id>$` | `writes$<thread_id>$<ns>$<checkpoint_id>$<task_id>$<idx>` |

The container requires a partition key path of `/partition_key`.

## License

MIT
