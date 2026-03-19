from __future__ import annotations

import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


def _claim_task(
    data_dir: str,
    task_id: str,
    agent_name: str,
    save_delay: float,
    result_queue,
) -> None:
    os.environ["CLAWTEAM_DATA_DIR"] = data_dir
    store = TaskStore("demo")
    original_save = TaskStore._save_unlocked

    def delayed_save(self, task):
        if save_delay:
            time.sleep(save_delay)
        return original_save(self, task)

    TaskStore._save_unlocked = delayed_save
    try:
        task = store.update(task_id, status=TaskStatus.in_progress, caller=agent_name)
        result_queue.put((agent_name, "ok", task.locked_by if task else None))
    except Exception as exc:
        result_queue.put((agent_name, "err", type(exc).__name__))
    finally:
        TaskStore._save_unlocked = original_save


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="requires fork start method")
def test_only_one_agent_can_claim_task_concurrently(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    store = TaskStore("demo")
    task = store.create("demo task")

    ctx = mp.get_context("fork")
    result_queue = ctx.Queue()

    proc_a = ctx.Process(
        target=_claim_task,
        args=(str(tmp_path), task.id, "agent-a", 0.3, result_queue),
    )
    proc_b = ctx.Process(
        target=_claim_task,
        args=(str(tmp_path), task.id, "agent-b", 0.0, result_queue),
    )

    proc_a.start()
    time.sleep(0.05)
    proc_b.start()

    results = sorted(result_queue.get(timeout=10) for _ in range(2))

    proc_a.join(timeout=10)
    proc_b.join(timeout=10)

    assert [result[1] for result in results].count("ok") == 1
    assert [result[1] for result in results].count("err") == 1
    assert any(result[2] == "TaskLockError" for result in results if result[1] == "err")

    final_task = TaskStore("demo").get(task.id)
    assert final_task is not None
    assert final_task.status == TaskStatus.in_progress
    assert final_task.locked_by in {"agent-a", "agent-b"}
