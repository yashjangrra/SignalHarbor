import asyncio
import pytest
from src.scheduler import PipelineScheduler
from src import config


def test_disabled_does_not_start(monkeypatch):
    monkeypatch.setattr(config, 'SCHEDULER_ENABLED', False, raising=False)
    scheduler = PipelineScheduler(None)
    scheduler.start()
    assert scheduler.scheduler is None


def test_nonoverlap_and_shutdown():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        async def pipeline():
            entered.set()
            await release.wait()
        scheduler = PipelineScheduler(pipeline)
        task = asyncio.create_task(scheduler.run())
        await entered.wait()
        assert await scheduler.run() == {'status': 'skipped_running'}
        await scheduler.stop()
        assert task.cancelled()
        assert not scheduler.run_lock.locked()
    asyncio.run(scenario())


def test_failure_is_observable_and_next_run_recovers():
    async def scenario():
        async def fail():
            raise RuntimeError('credential must not leak')
        scheduler = PipelineScheduler(fail)
        assert (await scheduler.run())['status'] == 'failed'
        assert 'credential' not in scheduler.last_error
        async def succeed():
            return {'status': 'complete'}
        scheduler.pipeline = succeed
        assert await scheduler.run() == {'status': 'complete'}
        assert scheduler.last_error is None
    asyncio.run(scenario())


def test_invalid_interval(monkeypatch):
    monkeypatch.setattr(config, 'SCHEDULER_ENABLED', True, raising=False)
    monkeypatch.setattr(config, 'SCOUT_INTERVAL_MINUTES', 0, raising=False)
    with pytest.raises(ValueError):
        PipelineScheduler(None).start()


def test_enabled_lifecycle_registers_bounded_interval_job(monkeypatch):
    monkeypatch.setattr(config, 'SCHEDULER_ENABLED', True, raising=False)
    monkeypatch.setattr(config, 'SCOUT_INTERVAL_MINUTES', 5, raising=False)
    async def scenario():
        async def pipeline():
            return {'status': 'complete'}
        scheduler = PipelineScheduler(pipeline)
        scheduler.start()
        job = scheduler.scheduler.get_job('scout-analyze')
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.trigger.interval.total_seconds() == 300
        assert scheduler.status()['running'] is True
        await scheduler.stop()
        await asyncio.sleep(0)
        assert scheduler.scheduler is None
    asyncio.run(scenario())


def test_real_scheduler_tick_executes_and_shutdown_cancels(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(config, 'SCHEDULER_ENABLED', True)
    monkeypatch.setattr(config, 'SCOUT_INTERVAL_MINUTES', 5)

    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def pipeline():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        scheduler = PipelineScheduler(pipeline)
        scheduler.start()
        native = scheduler.scheduler
        try:
            native.modify_job('scout-analyze', next_run_time=datetime.now(timezone.utc))
            await asyncio.wait_for(entered.wait(), 2)
            assert scheduler.status()['job_running'] is True
            assert await scheduler.run() == {'status': 'skipped_running'}
        finally:
            await scheduler.stop()
            await asyncio.sleep(0)
        assert cancelled.is_set()
        assert not native.running
        assert not scheduler.run_lock.locked()
        assert scheduler.scheduler is None
    asyncio.run(scenario())
