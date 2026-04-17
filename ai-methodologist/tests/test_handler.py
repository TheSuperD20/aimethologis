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
    assert task["status"] == "INTERVIEW"


def test_greeting_does_not_create_task(handler, mock_bot, mock_llm):
    handler.handle_message("expert1", "chan1", "привет", [])
    task = handler.state.get_task_by_channel("chan1")
    assert task is None
    mock_bot.send_message.assert_called_once()


def test_interview_moves_to_waiting_materials(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс", [])
    handler.handle_message("expert1", "chan1", "Цель: обучить новичков. ЦА: junior-разработчики.", [])
    task = handler.state.get_task_by_channel("chan1")
    assert task["status"] == "WAITING_MATERIALS"


def test_confirm_structure_starts_generation(handler, mock_bot, mock_llm):
    mock_llm.generate_structure.return_value = "1. Введение\n2. Основы"
    mock_llm.generate_longread.return_value = "# Курс\n\nТекст..."
    sm = handler.state
    task_id = sm.create_task("exp1", "chan1", "Python", "meth1", "mchan1")
    sm.update_task(task_id, status="STRUCTURE_PROPOSAL",
                   proposed_structure="1. Введение", source_text="текст материала")
    handler.handle_button(task_id, "confirm_structure", "exp1")
    task = sm.get_task(task_id)
    assert task["status"] == "REVIEW_EXPERT"


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
