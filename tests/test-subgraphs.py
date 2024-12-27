import pytest
from langgraph.graph import START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from typing import TypedDict


# Subgraph definitions
class SubgraphState(TypedDict):
    foo: str  # note that this key is shared with the parent graph state
    bar: str


def subgraph_node_1(state: SubgraphState):
    return {"bar": "bar"}


def subgraph_node_2(state: SubgraphState):
    return {"foo": state["foo"] + state["bar"]}


subgraph_builder = StateGraph(SubgraphState)
subgraph_builder.add_node(subgraph_node_1)
subgraph_builder.add_node(subgraph_node_2)
subgraph_builder.add_edge(START, "subgraph_node_1")
subgraph_builder.add_edge("subgraph_node_1", "subgraph_node_2")
subgraph = subgraph_builder.compile()


# Parent graph definitions
class State(TypedDict):
    foo: str


def node_1(state: State):
    return {"foo": "hi! " + state["foo"]}


builder = StateGraph(State)
builder.add_node("node_1", node_1)
builder.add_node("node_2", subgraph)
builder.add_edge(START, "node_1")
builder.add_edge("node_1", "node_2")

checkpointer = CosmosDBSaver(database_name="langgraph", container_name="checkpointtest")

graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "1"}}


# Test 1: Validate the state values from the graph streaming process
def test_graph_streaming():
    states = [chunk for _, chunk in graph.stream({"foo": "foo"}, config, subgraphs=True)]
    expected_outputs = [
        {'node_1': {'foo': 'hi! foo'}},
        {'subgraph_node_1': {'bar': 'bar'}},
        {'subgraph_node_2': {'foo': 'hi! foobar'}},
        {'node_2': {'foo': 'hi! foobar'}}
    ]
    for state, expected in zip(states, expected_outputs):
        assert state == expected


# Test 2: Validate the final state after subgraph processing
def test_subgraph_state():
    state_with_subgraph = [
        s for s in graph.get_state_history(config) if s.next == ("node_2",)
    ][0]
    subgraph_config = state_with_subgraph.tasks[0].state
    subgraph_state = graph.get_state(subgraph_config).values

    expected_subgraph_state = {'foo': 'hi! foobar', 'bar': 'bar'}
    assert subgraph_state == expected_subgraph_state


# Test 3: Validate the combined state from the parent and subgraph nodes
def test_combined_state():
    states = [chunk for _, chunk in graph.stream({"foo": "foo"}, config, subgraphs=True)]
    
    # Get combined state from both nodes (parent and subgraph)
    final_state = states[-1]  # The last state in the list should be the final combined state

    expected_final_state = {'node_2': {'foo': 'hi! foobar'}}
    assert final_state == expected_final_state
