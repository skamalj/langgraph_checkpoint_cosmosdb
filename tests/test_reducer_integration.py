"""
E2E test: CosmosDBSaver with MessageReducer integration.

Verifies that when a reducer is configured on CosmosDBSaver, the messages
stored in CosmosDB are capped at min_messages after pruning triggers.
"""
import os
import pytest
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from agentstate_reducer import MessageReducer


THREAD_ID = "reducer-e2e-test-001"
MIN_MESSAGES = 4
MAX_MESSAGES = 6


@pytest.fixture(scope="module")
def graph_with_reducer():
    reducer = MessageReducer(min_messages=MIN_MESSAGES, max_messages=MAX_MESSAGES)
    memory = CosmosDBSaver(
        database_name="langgraph",
        container_name="checkpointtest",
        reducer=reducer,
        messages_key="messages",
    )
    model = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

    def call_model(state: MessagesState):
        response = model.invoke(state["messages"])
        return {"messages": response}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_edge(START, "call_model")
    return builder.compile(checkpointer=memory), memory


def send(graph, config, text):
    result = None
    for chunk in graph.stream(
        {"messages": [{"type": "human", "content": text}]},
        config,
        stream_mode="values",
    ):
        result = chunk
    return result


def test_reducer_caps_stored_messages(graph_with_reducer):
    """
    Send enough messages to exceed max_messages, then confirm the checkpoint
    stored in CosmosDB holds no more than min_messages messages.
    """
    graph, memory = graph_with_reducer
    config = {"configurable": {"thread_id": THREAD_ID}}

    # Send MAX_MESSAGES + 2 turns to ensure pruning triggers at least once.
    prompts = [
        "My name is Kamal.",
        "I live in Roopnagar, Punjab.",
        "What is 2 + 2?",
        "Tell me a one-line joke.",
        "What colour is the sky?",
        "What did I say my name was?",
    ]
    for prompt in prompts:
        send(graph, config, prompt)

    # Read back the latest checkpoint directly from CosmosDB
    checkpoint_tuple = memory.get_tuple(config)
    assert checkpoint_tuple is not None, "No checkpoint found in CosmosDB"

    stored_messages = checkpoint_tuple.checkpoint["channel_values"].get("messages", [])
    print(f"\nStored message count: {len(stored_messages)}")
    for m in stored_messages:
        role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else "?")
        content = getattr(m, "content", None) or (m.get("content", "") if isinstance(m, dict) else "")
        print(f"  [{role}] {str(content)[:80]}")

    # preserve_first=True keeps index 0 regardless of role, so the floor is
    # min_messages (the sliding window) + 1 (the preserved first message).
    # Without a system prompt, index 0 is just the first human turn.
    expected_max = MIN_MESSAGES + 1
    assert len(stored_messages) <= expected_max, (
        f"Expected at most {expected_max} messages in checkpoint, "
        f"got {len(stored_messages)}"
    )


def test_reducer_preserves_recent_context(graph_with_reducer):
    """
    The last min_messages turns are retained, so the agent should recall
    facts from those turns. The final exchange before this test asked
    'What did I say my name was?' — name should still be in context.
    """
    graph, _ = graph_with_reducer
    config = {"configurable": {"thread_id": THREAD_ID}}

    result = send(graph, config, "Do you remember what my name is?")
    last_message = result["messages"][-1]
    content = getattr(last_message, "content", "")
    print(f"\nAgent reply: {content}")
    assert "kamal" in content.lower(), (
        f"Expected agent to recall name 'Kamal' from retained context, got: {content}"
    )
