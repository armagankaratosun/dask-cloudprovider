import pytest

import dask

nebius = pytest.importorskip("nebius")

from dask_cloudprovider.nebius.instances import NebiusCluster
from dask.distributed import Client
from distributed.core import Status


async def skip_without_credentials(config):
    if config.get("token") is None or config.get("project_id") is None:
        pytest.skip(
            """
        You must configure a Nebius AI Cloud API token to run this test.

        Either set this in your config

            # cloudprovider.yaml
            cloudprovider:
              nebius:
                token: "yourtoken"
                project_id: "yourprojectid"

        Or by setting it as an environment variable

            export DASK_CLOUDPROVIDER__NEBIUS__TOKEN=$(nebius iam get-access-token)
            export DASK_CLOUDPROVIDER__NEBIUS__PROJECT_ID=project_id

        """
        )


@pytest.fixture
async def config():
    return dask.config.get("cloudprovider.nebius", {})


@pytest.fixture
@pytest.mark.external
async def cluster(config):
    await skip_without_credentials(config)
    async with NebiusCluster(asynchronous=True, debug=True) as cluster:
        yield cluster


@pytest.mark.asyncio
@pytest.mark.external
async def test_init():
    cluster = NebiusCluster(asynchronous=True, debug=True)
    assert cluster.status == Status.created


@pytest.mark.asyncio
@pytest.mark.external
async def test_create_cluster(cluster):
    assert cluster.status == Status.running

    cluster.scale(1)
    await cluster
    assert len(cluster.workers) == 1

    async with Client(cluster, asynchronous=True) as client:

        def inc(x):
            return x + 1

        assert await client.submit(inc, 10).result() == 11


@pytest.mark.asyncio
async def test_get_cloud_init():
    cloud_init = NebiusCluster.get_cloud_init(
        docker_args="--privileged",
    )
    assert " --privileged " in cloud_init
