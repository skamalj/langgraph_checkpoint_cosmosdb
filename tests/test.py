import os
import getpass
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
import pytest

# Utility function to set environment variables
def _set_env(var: str):
    if not os.environ.get(var):
        os.environ[var] = getpass.getpass(f"{var}: ")

# Shared setup for model and memory
def setup_model():
    _set_env("OPENAI_API_KEY")
    return ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

def setup_memory():
    return CosmosDBSaver(database_name="langgraph", container_name="checkpointtest")

# Create a single graph for both storing and testing retrieval
def create_test_graph():
    memory = setup_memory()
    model = setup_model()

    def call_model(state: MessagesState):
        response = model.invoke(state["messages"])
        return {"messages": response}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_edge(START, "call_model")
    return builder.compile(checkpointer=memory)

# Helper to process a single message
def process_message(graph, config, input_message):
    responses = []
    for chunk in graph.stream({"messages": [input_message]}, config, stream_mode="values"):
        responses.append(chunk["messages"][-1].content)
    return responses

# Pytest test cases
@pytest.fixture(scope="module")
def test_graph():
    return create_test_graph()

@pytest.fixture(scope="module")
def config():
    return {"configurable": {"thread_id": "715"}}

# Test full flow: store and retrieve
def test_store_and_retrieve(test_graph, config):
    # Step 1: Provide information (store in memory)
    store_messages = [
        {"type": "user", "content": "Hi! I'm Kamal"},
        {"type": "user", "content": "I live in Roopnagar, Punjab"},
    ]
    for msg in store_messages:
        responses = process_message(test_graph, config, msg)
        assert responses, f"Failed to process message: {msg['content']}"

    # Step 2: Retrieve information
    retrieve_messages = [
        {"type": "user", "content": "Hello again"},
        {"type": "user", "content": "Tell me the history of my place?"},
    ]
    for msg in retrieve_messages:
        responses = process_message(test_graph, config, msg)
        # Verify that the stored information is referenced in the response
        print(responses)
        assert any(
            "Kamal" in response or "Roopnagar" in response for response in responses
        ), f"Failed to retrieve context for message: {msg['content']}"
