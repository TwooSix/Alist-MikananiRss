import pytest

from openlist_ani.bootstrap.runtime import AppRuntime


class _Component:
    async def run(self, *_args):
        return None

    async def stop(self):
        return None


@pytest.mark.asyncio
async def test_runtime_closes_owned_resources_even_if_start_never_completed():
    closed = []

    async def close_resource():
        closed.append(True)

    component = _Component()
    runtime = AppRuntime(
        scheduler=component,
        metadata_worker=component,
        download_workers=component,
        notification_worker=component,
        download_concurrency=1,
        notification_concurrency=1,
        close_callbacks=[close_resource],
    )

    await runtime.stop()
    await runtime.stop()

    assert closed == [True]
    assert runtime.health()["ready"] is False
