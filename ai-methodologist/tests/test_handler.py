import pytest
import os
from unittest.mock import MagicMock
from handler import Handler
from state import StateManager

TEST_DB = "test_handler.db"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.bot_user_id = "bot123"
    bot.send_message.return_value = "post123"
    bot.send_buttons.return_value = "post124"
    bot.get_dm_channel.return_value = "dm_channel_meth"
    return bot


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    llm.generate_longread.return_value = "# Лонгрид\n\nТекст..."
    return llm


@pytest.fixture
def handler(mock_bot, mock_llm):
    sm = StateManager(TEST_DB)
    return Handler(bot=mock_bot, state=sm, llm=mock_llm, methodologist_mm_id="meth_id")


def test_new_expert_message_creates_task(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс по Python", [])
    task = handler.state.get_task_by_channel("chan1")
    assert task is not None
    assert task["topic"] == "Python"
    assert task["status"] == "CHECKING_DUPLICATES"


def test_duplicate_check_sends_buttons(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс", [])
    mock_bot.send_buttons.assert_called_once()


def test_confirm_continue_moves_to_waiting_materials(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс", [])
    task = handler.state.get_task_by_channel("chan1")
    handler.handle_button(task["id"], "confirm_continue", "expert1")
    task = handler.state.get_task(task["id"])
    assert task["status"] == "WAITING_MATERIALS"


def test_cancel_moves_to_cancelled(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс", [])
    task = handler.state.get_task_by_channel("chan1")
    handler.handle_button(task["id"], "cancel", "expert1")
    task = handler.state.get_task(task["id"])
    assert task["status"] == "CANCELLED"


def test_approve_longread_moves_to_ask_test(handler, mock_bot, mock_llm):
    sm = handler.state
    task_id = sm.create_task("exp1", "chan1", "Python", "meth1", "mchan1")
    sm.update_task(task_id, status="REVIEW_EXPERT", longread="# Текст")
    handler.handle_button(task_id, "approve", "exp1")
    task = sm.get_task(task_id)
    assert task["status"] == "ASK_TEST"


def test_methodologist_approve_moves_to_done(handler, mock_bot, mock_llm):
    sm = handler.state
    task_id = sm.create_task("exp1", "chan1", "Python", "meth1", "mchan1")
    sm.update_task(task_id, status="REVIEW_METHODOLOGIST", longread="# Текст")
    handler.handle_button(task_id, "approve", "meth1")
    task = sm.get_task(task_id)
    assert task["status"] == "DONE"
