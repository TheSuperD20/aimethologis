import pytest
import json
from unittest.mock import MagicMock, patch
from services.llm import LLMService


@pytest.fixture
def llm():
    return LLMService(api_key="test-key")


def make_mock_response(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


def test_parse_intent_create_course(llm):
    mock_resp = make_mock_response('{"intent": "create_course", "entities": {"topic": "Основы Python"}}')
    with patch.object(llm.client.messages, "create", return_value=mock_resp):
        result = llm.parse_intent("Хочу сделать курс по основам Python")
    assert result["intent"] == "create_course"
    assert result["entities"]["topic"] == "Основы Python"


def test_parse_intent_returns_unknown_on_bad_json(llm):
    mock_resp = make_mock_response("не валидный JSON")
    with patch.object(llm.client.messages, "create", return_value=mock_resp):
        result = llm.parse_intent("непонятное сообщение")
    assert result["intent"] == "unknown"


def test_generate_longread_returns_string(llm):
    mock_resp = make_mock_response("# Заголовок\n\nТекст лонгрида...")
    with patch.object(llm.client.messages, "create", return_value=mock_resp):
        result = llm.generate_longread("Тема", "Исходный текст")
    assert "Заголовок" in result


def test_generate_test_quiz_returns_valid_json(llm):
    quiz_json = json.dumps({
        "type": "quiz",
        "questions": [{"question": "Q?", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "E"}]
    })
    mock_resp = make_mock_response(quiz_json)
    with patch.object(llm.client.messages, "create", return_value=mock_resp):
        result = llm.generate_test("# Лонгрид", "quiz")
    parsed = json.loads(result)
    assert parsed["type"] == "quiz"
    assert len(parsed["questions"]) == 1


def test_api_error_raises_llm_error(llm):
    with patch.object(llm.client.messages, "create", side_effect=Exception("API down")):
        with pytest.raises(Exception):
            llm.generate_longread("Тема", "Текст")
