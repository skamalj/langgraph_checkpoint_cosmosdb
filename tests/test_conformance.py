"""LangGraph's official checkpointer conformance suite (langgraph-checkpoint-conformance) against CosmosDBSaver.

Requires COSMOSDB_ENDPOINT / COSMOSDB_KEY; uses a throwaway container in the 'langgraph' database.
"""
import os
import uuid

import pytest
from langgraph.checkpoint.conformance import checkpointer_test
from langgraph.checkpoint.conformance.report import ProgressCallbacks
from langgraph.checkpoint.conformance.validate import validate

from langgraph_checkpoint_cosmosdb import CosmosDBSaver

pytestmark = pytest.mark.skipif(
    not (os.environ.get("COSMOSDB_ENDPOINT") and os.environ.get("COSMOSDB_KEY")), reason="Cosmos credentials not set"
)

_CONTAINER = f"conformance_{uuid.uuid4().hex[:8]}"


@checkpointer_test(name="CosmosDBSaver")
async def _saver():
    yield CosmosDBSaver(database_name="langgraph", container_name=_CONTAINER)


@pytest.mark.asyncio
async def test_official_conformance_base_capabilities():
    try:
        report = await validate(_saver, progress=ProgressCallbacks.quiet())
        failures = {cap: r.failures for cap, r in report.results.items() if r.failures}
        assert report.passed_all_base(), failures
        assert report.conformance_level() == "FULL"
    finally:
        from azure.cosmos import CosmosClient
        try:
            CosmosClient(os.environ["COSMOSDB_ENDPOINT"], credential=os.environ["COSMOSDB_KEY"]) \
                .get_database_client("langgraph").delete_container(_CONTAINER)
        except Exception:
            pass
