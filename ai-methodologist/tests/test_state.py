import pytest
import os
import uuid
from state import StateManager

TEST_DB = "test_bot.db"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.fixture
def sm():
    return StateManager(TEST_DB)


def test_create_and_get_task(sm):
    task_id = sm.create_task(
        expert_mm_id="user123",
        expert_channel_id="chan123",
        topic="Основы Python",
        methodologist_mm_id="meth456",
        methodologist_channel_id="mchan456",
    )
    task = sm.get_task(task_id)
    assert task["status"] == "INIT"
    assert task["topic"] == "Основы Python"
    assert task["expert_mm_id"] == "user123"


def test_update_status(sm):
    task_id = sm.create_task("u1", "c1", "Тема", "m1", "mc1")
    sm.update_task(task_id, status="WAITING_MATERIALS")
    task = sm.get_task(task_id)
    assert task["status"] == "WAITING_MATERIALS"


def test_get_task_by_channel(sm):
    task_id = sm.create_task("u1", "chan_expert_1", "Тема", "m1", "mc1")
    task = sm.get_task_by_channel("chan_expert_1")
    assert task["id"] == task_id


def test_get_task_by_channel_returns_none_for_done(sm):
    task_id = sm.create_task("u1", "chan1", "Тема", "m1", "mc1")
    sm.update_task(task_id, status="DONE")
    task = sm.get_task_by_channel("chan1")
    assert task is None


def test_update_longread(sm):
    task_id = sm.create_task("u1", "c1", "Тема", "m1", "mc1")
    sm.update_task(task_id, longread="# Лонгрид\n\nТекст...", longread_version=1)
    task = sm.get_task(task_id)
    assert task["longread"].startswith("# Лонгрид")
    assert task["longread_version"] == 1


def test_edit_counters_independent(sm):
    task_id = sm.create_task("u1", "c1", "Тема", "m1", "mc1")
    sm.update_task(task_id, longread_edit_count=3)
    sm.update_task(task_id, test_edit_count=1)
    task = sm.get_task(task_id)
    assert task["longread_edit_count"] == 3
    assert task["test_edit_count"] == 1
