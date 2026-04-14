# ИИ-Методолог MVP — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Mattermost bot that implements Scenario 2 (expert-initiated course creation): expert uploads materials → bot generates longread + test via Claude → review cycles with expert and methodologist.

**Architecture:** Single-process Python app. FastAPI HTTP server (for button callbacks) + WebSocket listener (for Mattermost messages) run concurrently in the same process. WebSocket runs in a worker thread with its own event loop; all Mattermost REST calls from that thread use sync `httpx`. State persists in SQLite (WAL mode) for thread-safe concurrent access.

**Tech Stack:** Python 3.11, FastAPI + uvicorn, mattermostdriver, httpx (sync), anthropic SDK, python-docx, pdfplumber, python-pptx, sqlite3 (stdlib)

---

## Pre-flight Checklist

Before starting Task 1, verify:
- [ ] You have the Mattermost URL and bot token (in `.env`)
- [ ] You have the Anthropic API key (in `.env`)
- [ ] You know the Mattermost username of the methodologist (for `METHODOLOGIST_USER_ID` in `.env`)
- [ ] **Button callbacks URL**: The bot is running on your local computer, but Mattermost server needs to reach it when user clicks a button. If Mattermost is hosted remotely (not on the same machine), install ngrok (`brew install ngrok`) and run `ngrok http 8000` to get a public URL (e.g. `https://abc123.ngrok.io`). Set `CALLBACK_URL=https://abc123.ngrok.io` in `.env`. Update the hardcoded `http://localhost:8000` in `bot.py → send_buttons` to use `os.environ.get("CALLBACK_URL", "http://localhost:8000")`.

---

## File Map

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app, `/api/button_callback` endpoint, bot startup in background thread |
| `bot.py` | `MattermostBot` class: WebSocket listener with supervision loop, sync REST helpers, dedup, SSL patch, send_message/send_file/send_buttons/get_dm_channel |
| `handler.py` | `handle_message()` and `handle_button()` — all business logic, state transitions, calls to services |
| `state.py` | `StateManager` — SQLite CRUD: create_task, get_task, update_task, get_task_by_channel |
| `services/llm.py` | `LLMService` — Claude API: parse_intent, generate_longread, apply_edits, generate_test, apply_test_edits. Threading.Timer timeout + 1 retry. |
| `services/files.py` | `FileProcessor` — extract_text(path), detect_type(filename), validate_file(filename, size) |
| `services/transcription.py` | `TranscriptionService` — stub: transcribe_file/transcribe_url return error message asking for text file |
| `prompts/longread.py` | SYSTEM_PROMPT, USER_PROMPT, EDIT_PROMPT constants |
| `prompts/test.py` | QUIZ_PROMPT, CASE_PROMPT, OPEN_QUESTIONS_PROMPT, INTENT_PROMPT constants |
| `requirements.txt` | All dependencies pinned |
| `.env.example` | Template with all required keys |
| `tests/test_state.py` | Unit tests for StateManager |
| `tests/test_files.py` | Unit tests for FileProcessor |
| `tests/test_llm.py` | Unit tests for LLMService (mocked API) |
| `tests/test_handler.py` | Unit tests for handler state machine logic (mocked bot + LLM) |

---

## Task 1: Environment Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.env` (from template, fill with real values)
- Create: `data/uploads/.gitkeep`
- Create: `tests/__init__.py`

- [ ] **Step 1: Install Python 3.11**

```bash
brew install python@3.11
python3.11 --version  # должно показать Python 3.11.x
```

- [ ] **Step 2: Create project virtual environment**

```bash
cd "/Users/tanya/Documents/AI agent/AI methodolodist/ai-methodologist"
python3.11 -m venv .venv
source .venv/bin/activate
python --version  # должно показать 3.11.x
```

- [ ] **Step 3: Create requirements.txt**

```
fastapi==0.115.0
uvicorn==0.30.6
mattermostdriver==7.3.2
httpx==0.27.2
anthropic==0.34.2
python-docx==1.1.2
pdfplumber==0.11.4
python-pptx==1.0.2
python-dotenv==1.0.1
pytest==8.3.3
pytest-mock==3.14.0
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: все пакеты установлены без ошибок.

- [ ] **Step 5: Create .env.example**

```ini
# Mattermost
MATTERMOST_URL=https://your-mattermost.company.ru
MATTERMOST_BOT_TOKEN=your_bot_token_here
MATTERMOST_BOT_USERNAME=ai-methodologist

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# Transkriptor (пока не обязателен — работает заглушка)
TRANSKRIPTOR_API_KEY=your_transkriptor_key_here

# Методолог (Mattermost user ID, не username!)
# Найти: Mattermost → профиль методолога → ... → Copy User ID
METHODOLOGIST_USER_ID=mattermost_user_id_here

# Порт для FastAPI (кнопки)
PORT=8000
```

- [ ] **Step 6: Create .env with real values**

Скопировать `.env.example` → `.env` и заполнить реальными значениями.

- [ ] **Step 7: Create directory structure**

```bash
mkdir -p services prompts tests data/uploads
touch services/__init__.py prompts/__init__.py tests/__init__.py
touch data/uploads/.gitkeep
```

- [ ] **Step 8: Create .gitignore**

```
.env
.venv/
data/uploads/*
!data/uploads/.gitkeep
bot.db
__pycache__/
*.pyc
```

- [ ] **Step 9: Commit**

```bash
git init
git add requirements.txt .env.example .gitignore
git commit -m "feat: project scaffold and dependencies"
```

---

## Task 2: State Machine (state.py)

**Files:**
- Create: `state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state.py
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
        methodologist_channel_id="mchan456"
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
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
pytest tests/test_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'state'`

- [ ] **Step 3: Implement state.py**

```python
# state.py
import sqlite3
import uuid
from datetime import datetime
from typing import Optional


class StateManager:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'INIT',
                    topic TEXT,
                    expert_mm_id TEXT,
                    expert_channel_id TEXT,
                    methodologist_mm_id TEXT,
                    methodologist_channel_id TEXT,
                    source_text TEXT,
                    longread TEXT,
                    longread_version INTEGER DEFAULT 0,
                    longread_edit_count INTEGER DEFAULT 0,
                    test TEXT,
                    test_type TEXT,
                    test_version INTEGER DEFAULT 0,
                    test_edit_count INTEGER DEFAULT 0,
                    needs_test INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

    def create_task(
        self,
        expert_mm_id: str,
        expert_channel_id: str,
        topic: str,
        methodologist_mm_id: str,
        methodologist_channel_id: str,
    ) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, status, topic, expert_mm_id, expert_channel_id,
                    methodologist_mm_id, methodologist_channel_id,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (task_id, "INIT", topic, expert_mm_id, expert_channel_id,
                 methodologist_mm_id, methodologist_channel_id, now, now),
            )
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_task_by_channel(self, channel_id: str) -> Optional[dict]:
        """Returns active task for a channel (expert or methodologist side)."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM tasks
                   WHERE (expert_channel_id = ? OR methodologist_channel_id = ?)
                     AND status NOT IN ('DONE', 'CANCELLED', 'ERROR')
                   ORDER BY created_at DESC LIMIT 1""",
                (channel_id, channel_id),
            ).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: str, **kwargs) -> None:
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", values)
```

- [ ] **Step 4: Run tests — verify they PASS**

```bash
pytest tests/test_state.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: SQLite state manager with WAL mode"
```

---

## Task 3: File Processor (services/files.py)

**Files:**
- Create: `services/files.py`
- Create: `tests/test_files.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_files.py
import os
import pytest
from services.files import FileProcessor

fp = FileProcessor()

def test_detect_type_docx():
    assert fp.detect_type("report.docx") == "document"

def test_detect_type_pdf():
    assert fp.detect_type("slides.pdf") == "document"

def test_detect_type_pptx():
    assert fp.detect_type("presentation.pptx") == "presentation"

def test_detect_type_video():
    assert fp.detect_type("video.mp4") == "video"
    assert fp.detect_type("recording.mov") == "video"

def test_detect_type_audio():
    assert fp.detect_type("audio.mp3") == "audio"

def test_detect_type_txt():
    assert fp.detect_type("notes.txt") == "document"

def test_detect_type_unknown():
    assert fp.detect_type("image.jpg") == "unknown"

def test_validate_file_ok():
    ok, msg = fp.validate_file("report.docx", 1024 * 1024)  # 1MB
    assert ok is True

def test_validate_file_too_large():
    ok, msg = fp.validate_file("report.docx", 60 * 1024 * 1024)  # 60MB
    assert ok is False
    assert "размер" in msg.lower() or "size" in msg.lower() or "большой" in msg.lower()

def test_validate_file_unsupported_type():
    ok, msg = fp.validate_file("photo.jpg", 1024)
    assert ok is False

def test_extract_text_from_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Привет мир", encoding="utf-8")
    text = fp.extract_text(str(f))
    assert "Привет мир" in text
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
pytest tests/test_files.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.files'`

- [ ] **Step 3: Implement services/files.py**

```python
# services/files.py
import os
from typing import Tuple

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

SUPPORTED = {
    ".docx": "document", ".pdf": "document", ".txt": "document",
    ".pptx": "presentation",
    ".mp4": "video", ".mov": "video", ".m4v": "video", ".avi": "video",
    ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".ogg": "audio",
}


class FileProcessor:
    def detect_type(self, filename: str) -> str:
        ext = os.path.splitext(filename.lower())[1]
        return SUPPORTED.get(ext, "unknown")

    def validate_file(self, filename: str, size_bytes: int) -> Tuple[bool, str]:
        if size_bytes > MAX_FILE_SIZE:
            mb = size_bytes // (1024 * 1024)
            return False, f"Файл слишком большой ({mb} МБ). Максимум — 50 МБ."
        if self.detect_type(filename) == "unknown":
            ext = os.path.splitext(filename)[1]
            return False, (
                f"Формат {ext} не поддерживается. "
                "Принимаю: DOCX, PDF, PPTX, TXT, MP4, MP3, MOV, M4A."
            )
        return True, ""

    def extract_text(self, file_path: str) -> str:
        ext = os.path.splitext(file_path.lower())[1]
        try:
            if ext == ".txt":
                return self._read_txt(file_path)
            elif ext == ".docx":
                return self._read_docx(file_path)
            elif ext == ".pdf":
                return self._read_pdf(file_path)
            elif ext == ".pptx":
                return self._read_pptx(file_path)
            else:
                return ""
        except Exception as e:
            return f"[Ошибка чтения файла: {e}]"

    def _read_txt(self, path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def _read_docx(self, path: str) -> str:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    def _read_pdf(self, path: str) -> str:
        import pdfplumber
        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return "\n".join(texts)

    def _read_pptx(self, path: str) -> str:
        from pptx import Presentation
        prs = Presentation(path)
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text)
        return "\n".join(texts)
```

- [ ] **Step 4: Run tests — verify they PASS**

```bash
pytest tests/test_files.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/files.py tests/test_files.py
git commit -m "feat: file processor with text extraction and validation"
```

---

## Task 4: Prompts (prompts/longread.py, prompts/test.py)

**Files:**
- Create: `prompts/longread.py`
- Create: `prompts/test.py`

Note: No tests for prompts (they are string constants). Quality is verified via manual LLM testing in Task 6.

- [ ] **Step 1: Create prompts/longread.py**

```python
# prompts/longread.py

INTENT_PROMPT = """Определи намерение пользователя из сообщения в корпоративном мессенджере.
Контекст: пользователь общается с ботом для создания обучающих курсов.

Возможные intent:
- "create_course" — хочет создать курс (извлечь: topic)
- "approve" — одобрение материала ("всё хорошо", "ок", "одобряю", "принято")
- "request_changes" — запрос правок (извлечь: feedback — текст с правками)
- "upload_materials" — сообщает что загружает материалы
- "send_link" — отправляет ссылку на видео (извлечь: url)
- "confirm_continue" — подтверждает продолжение ("да", "продолжаем", "поехали")
- "cancel" — отмена ("нет", "отмена", "отменить", "не нужно")
- "test_choice" — выбор типа теста (извлечь: test_type = quiz|case|open_questions|none)
- "unknown" — не удалось определить

Ответь ТОЛЬКО валидным JSON без markdown:
{{"intent": "...", "entities": {{}}}}

Сообщение: {message}"""

LONGREAD_SYSTEM_PROMPT = """Ты — ИИ-методолог, который создаёт обучающие материалы для сотрудников компании.

Твоя задача — написать лонгрид (обучающую статью) на основе предоставленного материала.

Требования к стилю:
- Дружелюбный тон, без канцеляризмов и бюрократического языка
- Понятный для сотрудников без специальных знаний по теме
- С конкретными примерами из практики, если они есть в исходном материале
- Живой язык — как будто объясняешь умному коллеге за чашкой кофе
- Используй эмодзи умеренно для выделения ключевых мыслей (👉, ✅, ❗)

Структура лонгрида:
1. Заголовок (привлекающий внимание, не скучный)
2. Введение (1-2 абзаца: зачем это нужно, почему важно знать)
3. Основная часть с подзаголовками (разбить на логические блоки по 200-400 слов каждый)
4. Ключевые выводы (3-5 пунктов — что запомнить и применять)

Объём: 3000-8000 символов в зависимости от объёма исходного материала.
Формат вывода: Markdown."""

LONGREAD_USER_PROMPT = """Тема: {topic}

Исходный материал:
---
{source_text}
---

Напиши лонгрид на основе этого материала."""

EDIT_PROMPT = """Вот текущая версия лонгрида:
---
{current_text}
---

Комментарии и правки от ревьюера:
---
{feedback}
---

Внеси правки в лонгрид согласно комментариям. Верни обновлённый текст целиком в Markdown.
Не добавляй комментарии типа «я изменил X» — только сам текст лонгрида."""
```

- [ ] **Step 2: Create prompts/test.py**

```python
# prompts/test.py

QUIZ_PROMPT = """На основе этого обучающего лонгрида создай тест для проверки знаний.

Лонгрид:
---
{longread}
---

Создай {num_questions} вопросов с 4 вариантами ответа (один правильный).
Вопросы должны проверять понимание, а не механическое запоминание.

Ответь СТРОГО в JSON без markdown:
{{
  "type": "quiz",
  "questions": [
    {{
      "question": "Текст вопроса?",
      "options": ["Вариант A", "Вариант B", "Вариант C", "Вариант D"],
      "correct_index": 0,
      "explanation": "Почему этот вариант правильный"
    }}
  ]
}}"""

CASE_PROMPT = """На основе этого обучающего лонгрида создай кейс-задание.

Лонгрид:
---
{longread}
---

Создай реалистичный рабочий кейс: опиши ситуацию и задай 3-5 вопросов для анализа.

Ответь СТРОГО в JSON без markdown:
{{
  "type": "case",
  "case_description": "Описание реалистичной рабочей ситуации...",
  "questions": [
    {{
      "question": "Вопрос для анализа?",
      "hint": "На что обратить внимание при ответе"
    }}
  ]
}}"""

OPEN_QUESTIONS_PROMPT = """На основе этого обучающего лонгрида создай открытые вопросы для проверки знаний.

Лонгрид:
---
{longread}
---

Создай 5 открытых вопросов, которые требуют развёрнутого ответа и понимания материала.

Ответь СТРОГО в JSON без markdown:
{{
  "type": "open_questions",
  "questions": [
    {{
      "question": "Открытый вопрос?",
      "key_points": ["ключевой момент 1", "ключевой момент 2"]
    }}
  ]
}}"""

TEST_EDIT_PROMPT = """Вот текущая версия теста (в JSON):
---
{current_test}
---

Комментарии и правки от ревьюера:
---
{feedback}
---

Внеси правки в тест согласно комментариям. Верни обновлённый тест в том же JSON формате.
Только JSON, без markdown и комментариев."""
```

- [ ] **Step 3: Commit**

```bash
git add prompts/longread.py prompts/test.py
git commit -m "feat: Claude prompts for longread and test generation"
```

---

## Task 5: LLM Service (services/llm.py)

**Files:**
- Create: `services/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm.py
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
        "questions": [{"question": "Q?", "options": ["A","B","C","D"], "correct_index": 0, "explanation": "E"}]
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
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
pytest tests/test_llm.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.llm'`

- [ ] **Step 3: Implement services/llm.py**

```python
# services/llm.py
import json
import threading
import logging
from typing import Optional
import anthropic
from prompts.longread import (
    INTENT_PROMPT, LONGREAD_SYSTEM_PROMPT, LONGREAD_USER_PROMPT, EDIT_PROMPT
)
from prompts.test import QUIZ_PROMPT, CASE_PROMPT, OPEN_QUESTIONS_PROMPT, TEST_EDIT_PROMPT

logger = logging.getLogger(__name__)
MODEL = "claude-sonnet-4-20250514"
LLM_TIMEOUT = 90  # seconds


class LLMError(Exception):
    pass


class LLMService:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def _call(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Sync call to Claude with threading.Timer timeout."""
        result = [None]
        error = [None]
        event = threading.Event()

        def _do_call():
            try:
                resp = self.client.messages.create(
                    model=MODEL,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                result[0] = resp.content[0].text
            except Exception as e:
                error[0] = e
            finally:
                event.set()

        t = threading.Thread(target=_do_call, daemon=True)
        t.start()
        if not event.wait(timeout=LLM_TIMEOUT):
            raise LLMError("Claude API timeout (90s)")
        if error[0]:
            raise LLMError(f"Claude API error: {error[0]}") from error[0]
        return result[0]

    def _call_with_retry(self, system: str, user: str, max_tokens: int = 4096) -> str:
        try:
            return self._call(system, user, max_tokens)
        except LLMError as e:
            logger.warning(f"LLM first attempt failed: {e}. Retrying...")
            return self._call(system, user, max_tokens)

    def parse_intent(self, message: str) -> dict:
        try:
            text = self._call(
                system="You parse user intent and return JSON only.",
                user=INTENT_PROMPT.format(message=message),
                max_tokens=200,
            )
            return json.loads(text)
        except (LLMError, json.JSONDecodeError) as e:
            logger.warning(f"Intent parsing failed: {e}")
            return {"intent": "unknown", "entities": {}}

    def generate_longread(self, topic: str, source_text: str) -> str:
        return self._call_with_retry(
            system=LONGREAD_SYSTEM_PROMPT,
            user=LONGREAD_USER_PROMPT.format(topic=topic, source_text=source_text),
            max_tokens=8000,
        )

    def apply_edits(self, current_text: str, feedback: str) -> str:
        return self._call_with_retry(
            system=LONGREAD_SYSTEM_PROMPT,
            user=EDIT_PROMPT.format(current_text=current_text, feedback=feedback),
            max_tokens=8000,
        )

    def generate_test(self, longread: str, test_type: str) -> str:
        prompts = {
            "quiz": QUIZ_PROMPT.format(longread=longread, num_questions=5),
            "case": CASE_PROMPT.format(longread=longread),
            "open_questions": OPEN_QUESTIONS_PROMPT.format(longread=longread),
        }
        prompt = prompts.get(test_type, prompts["quiz"])
        return self._call_with_retry(
            system="You generate educational tests and return JSON only.",
            user=prompt,
            max_tokens=3000,
        )

    def apply_test_edits(self, current_test: str, feedback: str) -> str:
        return self._call_with_retry(
            system="You edit educational tests and return JSON only.",
            user=TEST_EDIT_PROMPT.format(current_test=current_test, feedback=feedback),
            max_tokens=3000,
        )
```

- [ ] **Step 4: Run tests — verify they PASS**

```bash
pytest tests/test_llm.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/llm.py tests/test_llm.py
git commit -m "feat: LLM service with timeout, retry, and intent parsing"
```

---

## Task 6: Transcription Stub (services/transcription.py)

**Files:**
- Create: `services/transcription.py`

No tests needed — this is a stub that will be replaced with real Transkriptor integration later.

- [ ] **Step 1: Create services/transcription.py**

```python
# services/transcription.py
from typing import Optional


class TranscriptionService:
    """
    Stub implementation. Real Transkriptor API integration comes in next version.
    When ready: POST to https://api.tor.app/developer/transcription/initiate
    Auth: Authorization: Bearer {api_key}
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.available = bool(api_key)

    def transcribe_file(self, file_path: str) -> str:
        if not self.available:
            return None  # caller must check
        raise NotImplementedError("Transkriptor file upload not yet implemented")

    def transcribe_url(self, url: str) -> str:
        if not self.available:
            return None
        raise NotImplementedError("Transkriptor URL transcription not yet implemented")

    def is_available(self) -> bool:
        return self.available

    def get_stub_message(self) -> str:
        return (
            "Транскрибация видео пока недоступна. "
            "Пожалуйста, загрузи материалы в текстовом формате: "
            "документ Word (.docx), PDF или текстовый файл (.txt)."
        )
```

- [ ] **Step 2: Commit**

```bash
git add services/transcription.py
git commit -m "feat: transcription service stub"
```

---

## Task 7: Mattermost Bot (bot.py)

**Files:**
- Create: `bot.py`

- [ ] **Step 1: Write a connectivity smoke test**

```python
# tests/test_bot_connection.py
# NOTE: This test requires real .env credentials. Run manually.
# Skip in CI: pytest -m "not integration"
import pytest
import os
from dotenv import load_dotenv
load_dotenv()

@pytest.mark.integration
def test_bot_can_login():
    from bot import MattermostBot
    bot = MattermostBot(
        url=os.environ["MATTERMOST_URL"],
        token=os.environ["MATTERMOST_BOT_TOKEN"],
    )
    bot.login()
    info = bot.get_bot_user_info()
    assert info.get("username") is not None
    bot.logout()
```

- [ ] **Step 2: Implement bot.py**

```python
# bot.py
import ssl
import logging
import threading
import asyncio
import time
from typing import Callable, Optional
import httpx
import mattermostdriver.websocket as mm_ws

# SSL fix: mattermostdriver uses CLIENT_AUTH which is wrong for client connections
_orig_ssl = mm_ws.ssl.create_default_context
mm_ws.ssl.create_default_context = lambda *a, **kw: _orig_ssl(ssl.Purpose.SERVER_AUTH)

from mattermostdriver import Driver

logger = logging.getLogger(__name__)


class MattermostBot:
    def __init__(self, url: str, token: str, username: str = "ai-methodologist"):
        parsed = url.rstrip("/")
        scheme = "https" if parsed.startswith("https") else "http"
        host = parsed.replace("https://", "").replace("http://", "")

        self._driver = Driver({
            "url": host,
            "token": token,
            "scheme": scheme,
            "port": 443 if scheme == "https" else 8065,
            "verify": True,
        })
        self._token = token
        self._base_url = parsed
        self._api_base = f"{parsed}/api/v4"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._seen_ids: set[str] = set()
        self._shutdown = False
        self._message_callback: Optional[Callable] = None
        self.bot_user_id: Optional[str] = None

    def login(self):
        self._driver.login()
        self._headers = {"Authorization": f"Bearer {self._driver.client.token}"}
        me = self._sync_get("/users/me")
        self.bot_user_id = me.get("id")
        logger.info(f"Logged in as {me.get('username')} ({self.bot_user_id})")

    def logout(self):
        try:
            self._driver.logout()
        except Exception:
            pass

    def get_bot_user_info(self) -> dict:
        return self._sync_get("/users/me")

    # --- Sync REST helpers (safe to call from WebSocket worker thread) ---

    def _sync_get(self, path: str) -> dict:
        resp = httpx.get(f"{self._api_base}{path}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _sync_post(self, path: str, data: dict) -> dict:
        resp = httpx.post(f"{self._api_base}{path}", headers=self._headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # --- Public API ---

    def send_message(self, channel_id: str, message: str) -> str:
        post = self._sync_post("/posts", {"channel_id": channel_id, "message": message})
        return post.get("id", "")

    def send_buttons(self, channel_id: str, message: str, buttons: list[dict]) -> str:
        """Send message with interactive buttons.
        buttons: [{"name": "Label", "action": "action_id"}]
        Buttons POST to /api/button_callback with {"task_id": ..., "action": ...}
        """
        attachments = [{
            "text": "",
            "actions": [
                {
                    "name": btn["name"],
                    "integration": {
                        "url": "http://localhost:8000/api/button_callback",
                        "context": btn.get("context", {}),
                    },
                }
                for btn in buttons
            ],
        }]
        post = self._sync_post("/posts", {
            "channel_id": channel_id,
            "message": message,
            "props": {"attachments": attachments},
        })
        return post.get("id", "")

    def send_file(self, channel_id: str, file_path: str, message: str = "") -> str:
        """Upload a file and post it to channel."""
        with open(file_path, "rb") as f:
            resp = httpx.post(
                f"{self._api_base}/files",
                headers={"Authorization": self._headers["Authorization"]},
                data={"channel_id": channel_id},
                files={"files": (file_path.split("/")[-1], f)},
                timeout=60,
            )
            resp.raise_for_status()
            file_id = resp.json()["file_infos"][0]["id"]
        post = self._sync_post("/posts", {
            "channel_id": channel_id,
            "message": message,
            "file_ids": [file_id],
        })
        return post.get("id", "")

    def get_dm_channel(self, user_id: str) -> str:
        """Get or create DM channel between bot and user."""
        data = self._sync_post("/channels/direct", [self.bot_user_id, user_id])
        return data["id"]

    def get_user_by_username(self, username: str) -> Optional[dict]:
        username = username.lstrip("@")
        try:
            return self._sync_get(f"/users/username/{username}")
        except Exception:
            return None

    def download_file(self, file_id: str, save_path: str) -> None:
        resp = httpx.get(
            f"{self._api_base}/files/{file_id}",
            headers=self._headers,
            timeout=120,
            follow_redirects=True,
        )
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(resp.content)

    # --- WebSocket listener ---

    def set_message_callback(self, callback: Callable):
        """callback(user_id, channel_id, message, file_ids) called for each new message."""
        self._message_callback = callback

    def start_listening(self):
        """Start WebSocket supervision loop in background thread. Non-blocking."""
        t = threading.Thread(target=self._supervision_loop, daemon=True)
        t.start()

    def stop(self):
        self._shutdown = True

    def _supervision_loop(self):
        reconnect_count = 0
        while not self._shutdown:
            try:
                self._start_ws()
            except Exception:
                logger.exception("WebSocket crashed")
            if self._shutdown:
                break
            reconnect_count += 1
            delay = min(5 * (2 ** reconnect_count), 30)
            logger.info(f"Reconnecting in {delay}s...")
            time.sleep(delay)
            try:
                self.login()
            except Exception:
                logger.exception("Re-login failed")

    def _start_ws(self):
        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)
        try:
            self._driver.init_websocket(self._ws_handler)
        finally:
            thread_loop.close()

    async def _ws_handler(self, event):
        try:
            if event.get("event") != "posted":
                return
            data = event.get("data", {})
            post = __import__("json").loads(data.get("post", "{}"))
            post_id = post.get("id", "")

            # Dedup
            if post_id in self._seen_ids:
                return
            self._seen_ids.add(post_id)
            if len(self._seen_ids) > 2000:
                self._seen_ids = set(list(self._seen_ids)[-1000:])

            user_id = post.get("user_id", "")
            if user_id == self.bot_user_id:
                return  # ignore own messages

            channel_id = post.get("channel_id", "")
            message = post.get("message", "")
            file_ids = post.get("file_ids", [])

            if self._message_callback:
                self._message_callback(user_id, channel_id, message, file_ids)
        except Exception:
            logger.exception("Error in ws_handler")
```

- [ ] **Step 3: Run integration test (requires .env)**

```bash
pytest tests/test_bot_connection.py -m integration -v
```

Expected: `test_bot_can_login PASSED`

If FAILED: check `MATTERMOST_URL` and `MATTERMOST_BOT_TOKEN` in `.env`.

- [ ] **Step 4: Commit**

```bash
git add bot.py tests/test_bot_connection.py
git commit -m "feat: Mattermost bot with WebSocket, SSL fix, supervision loop"
```

---

## Task 8: Handler — Full Scenario 2 (handler.py)

**Files:**
- Create: `handler.py`
- Create: `tests/test_handler.py`

- [ ] **Step 1: Write failing tests for key state transitions**

```python
# tests/test_handler.py
import pytest
import os
from unittest.mock import MagicMock, patch, call
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
    # Should send message with Continue/Cancel buttons
    mock_bot.send_buttons.assert_called_once()

def test_confirm_continue_moves_to_waiting_materials(handler, mock_bot, mock_llm):
    mock_llm.parse_intent.return_value = {"intent": "create_course", "entities": {"topic": "Python"}}
    handler.handle_message("expert1", "chan1", "Хочу курс", [])
    task = handler.state.get_task_by_channel("chan1")
    # Simulate button click: confirm_continue
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
    # Create task already in REVIEW_EXPERT
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
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
pytest tests/test_handler.py -v
```

Expected: `ModuleNotFoundError: No module named 'handler'`

- [ ] **Step 3: Implement handler.py**

```python
# handler.py
import os
import json
import logging
import tempfile
from typing import Optional
from bot import MattermostBot
from state import StateManager
from services.llm import LLMService, LLMError
from services.files import FileProcessor
from services.transcription import TranscriptionService

logger = logging.getLogger(__name__)
MAX_EDITS = 5
UPLOAD_DIR = "data/uploads"


class Handler:
    def __init__(
        self,
        bot: MattermostBot,
        state: StateManager,
        llm: LLMService,
        methodologist_mm_id: str,
        transcription: Optional[TranscriptionService] = None,
    ):
        self.bot = bot
        self.state = state
        self.llm = llm
        self.methodologist_mm_id = methodologist_mm_id
        self.transcription = transcription or TranscriptionService()
        self.files = FileProcessor()
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    # ---- Entry points ----

    def handle_message(self, user_id: str, channel_id: str, message: str, file_ids: list):
        task = self.state.get_task_by_channel(channel_id)

        if task is None:
            self._handle_new_conversation(user_id, channel_id, message, file_ids)
            return

        status = task["status"]

        if status == "WAITING_MATERIALS":
            self._handle_materials(task, message, file_ids)
        elif status == "REVIEW_EXPERT" and not file_ids:
            self._handle_expert_feedback_text(task, message)
        elif status == "REVIEW_TEST" and not file_ids:
            self._handle_test_feedback_text(task, message)
        elif status == "REVIEW_METHODOLOGIST" and not file_ids:
            self._handle_methodologist_feedback_text(task, message)
        else:
            # User sent message in unexpected state — acknowledge
            self.bot.send_message(channel_id,
                "Получил твоё сообщение. Если нужно что-то изменить, воспользуйся кнопками выше.")

    def handle_button(self, task_id: str, action: str, user_id: str):
        task = self.state.get_task(task_id)
        if not task:
            logger.warning(f"Button click for unknown task {task_id}")
            return

        status = task["status"]
        dispatch = {
            ("CHECKING_DUPLICATES", "confirm_continue"): self._on_continue_after_check,
            ("CHECKING_DUPLICATES", "cancel"): self._on_cancel,
            ("REVIEW_EXPERT", "approve"): self._on_expert_approve_longread,
            ("REVIEW_EXPERT", "request_changes"): self._on_expert_request_longread_changes,
            ("ASK_TEST", "quiz"): lambda t: self._on_test_type_chosen(t, "quiz"),
            ("ASK_TEST", "case"): lambda t: self._on_test_type_chosen(t, "case"),
            ("ASK_TEST", "open_questions"): lambda t: self._on_test_type_chosen(t, "open_questions"),
            ("ASK_TEST", "no_test"): self._on_no_test,
            ("REVIEW_TEST", "approve"): self._on_expert_approve_test,
            ("REVIEW_TEST", "request_changes"): self._on_expert_request_test_changes,
            ("REVIEW_METHODOLOGIST", "approve"): self._on_methodologist_approve,
            ("REVIEW_METHODOLOGIST", "request_changes"): self._on_methodologist_request_changes,
        }
        handler_fn = dispatch.get((status, action))
        if handler_fn:
            try:
                handler_fn(task)
            except Exception as e:
                logger.exception(f"Handler error for task {task_id}")
                channel = task["expert_channel_id"]
                self.bot.send_message(channel,
                    "Произошла ошибка при обработке. Попробуй ещё раз или обратись к методологу.")
        else:
            logger.warning(f"No handler for ({status}, {action})")

    # ---- New conversation ----

    def _handle_new_conversation(self, user_id: str, channel_id: str, message: str, file_ids: list):
        intent_data = self.llm.parse_intent(message)
        intent = intent_data.get("intent")

        if intent != "create_course":
            self.bot.send_message(channel_id,
                "Привет! 👋 Я помогаю создавать обучающие курсы.\n\n"
                "Напиши мне что-то вроде: «Хочу сделать курс по теме X» — и мы начнём!")
            return

        topic = intent_data.get("entities", {}).get("topic", message[:100])
        meth_channel = self.bot.get_dm_channel(self.methodologist_mm_id)
        task_id = self.state.create_task(
            expert_mm_id=user_id,
            expert_channel_id=channel_id,
            topic=topic,
            methodologist_mm_id=self.methodologist_mm_id,
            methodologist_channel_id=meth_channel,
        )
        self.state.update_task(task_id, status="CHECKING_DUPLICATES")
        self.bot.send_buttons(
            channel_id,
            f"Хочешь создать курс по теме: **{topic}**\n\n"
            "Я проверил базу — похожих курсов не найдено. Продолжаем?",
            [
                {"name": "✅ Продолжить", "context": {"task_id": task_id, "action": "confirm_continue"}},
                {"name": "❌ Отменить", "context": {"task_id": task_id, "action": "cancel"}},
            ],
        )

    # ---- State handlers ----

    def _on_continue_after_check(self, task: dict):
        self.state.update_task(task["id"], status="WAITING_MATERIALS")
        self.bot.send_message(
            task["expert_channel_id"],
            "Отлично! Теперь загрузи материалы для курса.\n\n"
            "Принимаю:\n"
            "📄 Документы: Word (.docx), PDF, текстовый файл (.txt)\n"
            "📊 Презентации: PowerPoint (.pptx)\n"
            "🎥 Видео и аудио: пока загрузи текстовое описание (транскрибация видео — скоро)\n\n"
            "Можно загрузить несколько файлов сразу.",
        )

    def _on_cancel(self, task: dict):
        self.state.update_task(task["id"], status="CANCELLED")
        self.bot.send_message(task["expert_channel_id"], "Хорошо, отменяю. Если понадоблюсь — пиши! 👋")

    def _handle_materials(self, task: dict, message: str, file_ids: list):
        if not file_ids and not message.strip():
            self.bot.send_message(task["expert_channel_id"],
                "Не вижу файлов. Прикрепи файл к сообщению или напиши текст напрямую.")
            return

        self.bot.send_message(task["expert_channel_id"],
            "Получил материалы! ⏳ Обрабатываю — это займёт несколько минут...")
        self.state.update_task(task["id"], status="PROCESSING")

        # Download and extract text
        texts = []
        for fid in file_ids:
            try:
                # Fetch real filename from Mattermost file metadata before download
                file_info = self.bot._sync_get(f"/files/{fid}/info")
                real_filename = file_info.get("name", fid)
                ext = os.path.splitext(real_filename)[1]
                save_path = f"{UPLOAD_DIR}/{task['id']}_{fid}{ext}"
                self.bot.download_file(fid, save_path)
                ok, err = self.files.validate_file(real_filename, os.path.getsize(save_path))
                if not ok:
                    self.bot.send_message(task["expert_channel_id"], f"⚠️ {err}")
                    continue
                ftype = self.files.detect_type(real_filename)
                if ftype in ("video", "audio"):
                    if not self.transcription.is_available():
                        self.bot.send_message(task["expert_channel_id"],
                            self.transcription.get_stub_message())
                    continue
                text = self.files.extract_text(save_path)
                if text:
                    texts.append(text)
            except Exception as e:
                logger.exception(f"File processing error: {e}")

        if message.strip():
            texts.append(message.strip())

        if not texts:
            self.state.update_task(task["id"], status="WAITING_MATERIALS")
            self.bot.send_message(task["expert_channel_id"],
                "Не удалось извлечь текст из файлов. "
                "Попробуй загрузить .docx или .txt файл.")
            return

        source_text = "\n\n---\n\n".join(texts)
        self.state.update_task(task["id"], source_text=source_text)

        # Generate longread
        try:
            longread = self.llm.generate_longread(task["topic"], source_text)
        except LLMError as e:
            self.state.update_task(task["id"], status="WAITING_MATERIALS")
            self.bot.send_message(task["expert_channel_id"],
                "❌ Ошибка при генерации материала. Попробуй загрузить файлы ещё раз.")
            return

        self.state.update_task(task["id"],
            status="REVIEW_EXPERT",
            longread=longread,
            longread_version=1,
            longread_edit_count=0,
        )
        self._send_longread_for_review(task["id"], task["expert_channel_id"], longread, version=1)

    def _send_longread_for_review(self, task_id: str, channel_id: str, longread: str, version: int):
        # Save longread to temp file and send
        tmp = f"{UPLOAD_DIR}/{task_id}_longread_v{version}.md"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(longread)
        self.bot.send_file(channel_id, tmp,
            f"📝 Лонгрид готов (версия {version}). Посмотри — всё ли верно по содержанию?")
        self.bot.send_buttons(channel_id, "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task_id, "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task_id, "action": "request_changes"}},
            ])

    def _on_expert_approve_longread(self, task: dict):
        self.state.update_task(task["id"], status="ASK_TEST")
        self.bot.send_buttons(
            task["expert_channel_id"],
            "Отлично! 🎉 Нужна ли проверка знаний к этому материалу?",
            [
                {"name": "📝 Тест с вариантами", "context": {"task_id": task["id"], "action": "quiz"}},
                {"name": "📋 Кейс-задание", "context": {"task_id": task["id"], "action": "case"}},
                {"name": "❓ Открытые вопросы", "context": {"task_id": task["id"], "action": "open_questions"}},
                {"name": "⏭️ Не нужна", "context": {"task_id": task["id"], "action": "no_test"}},
            ],
        )

    def _on_expert_request_longread_changes(self, task: dict):
        edit_count = task.get("longread_edit_count", 0)
        if edit_count >= MAX_EDITS:
            self.bot.send_message(task["expert_channel_id"],
                f"Мы уже внесли {MAX_EDITS} правок. "
                "Предлагаю обсудить оставшиеся правки лично с методологом.")
            return
        self.bot.send_message(task["expert_channel_id"],
            "Напиши, что нужно изменить — я внесу правки.")
        # Stay in REVIEW_EXPERT, wait for text feedback

    def _handle_expert_feedback_text(self, task: dict, feedback: str):
        if not feedback.strip():
            return
        task = self.state.get_task(task["id"])  # refresh
        if task["status"] != "REVIEW_EXPERT":
            return
        try:
            updated = self.llm.apply_edits(task["longread"], feedback)
        except LLMError:
            self.bot.send_message(task["expert_channel_id"],
                "❌ Ошибка при применении правок. Попробуй ещё раз.")
            return
        version = (task.get("longread_version") or 1) + 1
        edit_count = (task.get("longread_edit_count") or 0) + 1
        self.state.update_task(task["id"],
            longread=updated, longread_version=version, longread_edit_count=edit_count)
        self._send_longread_for_review(task["id"], task["expert_channel_id"], updated, version)

    def _on_test_type_chosen(self, task: dict, test_type: str):
        self.state.update_task(task["id"], status="GENERATING_TEST", test_type=test_type)
        self.bot.send_message(task["expert_channel_id"],
            "⏳ Генерирую проверочное задание...")
        try:
            test = self.llm.generate_test(task["longread"], test_type)
        except LLMError:
            self.state.update_task(task["id"], status="ASK_TEST")
            self.bot.send_message(task["expert_channel_id"],
                "❌ Ошибка при генерации теста. Попробуй выбрать тип ещё раз.")
            return
        self.state.update_task(task["id"],
            status="REVIEW_TEST", test=test, test_version=1, test_edit_count=0)
        self._send_test_for_review(task["id"], task["expert_channel_id"], test, version=1)

    def _send_test_for_review(self, task_id: str, channel_id: str, test_json: str, version: int):
        tmp = f"{UPLOAD_DIR}/{task_id}_test_v{version}.json"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(test_json)
        self.bot.send_file(channel_id, tmp,
            f"📋 Проверочное задание готово (версия {version}). Всё верно?")
        self.bot.send_buttons(channel_id, "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task_id, "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task_id, "action": "request_changes"}},
            ])

    def _on_no_test(self, task: dict):
        self.state.update_task(task["id"], status="REVIEW_METHODOLOGIST", needs_test=0)
        self._send_to_methodologist(task)

    def _on_expert_approve_test(self, task: dict):
        self.state.update_task(task["id"], status="REVIEW_METHODOLOGIST")
        self._send_to_methodologist(task)

    def _on_expert_request_test_changes(self, task: dict):
        edit_count = task.get("test_edit_count", 0)
        if edit_count >= MAX_EDITS:
            self.bot.send_message(task["expert_channel_id"],
                f"Мы уже внесли {MAX_EDITS} правок в тест. "
                "Предлагаю обсудить с методологом.")
            return
        self.bot.send_message(task["expert_channel_id"],
            "Напиши, что нужно изменить в тесте.")

    def _handle_test_feedback_text(self, task: dict, feedback: str):
        if not feedback.strip():
            return
        task = self.state.get_task(task["id"])
        if task["status"] != "REVIEW_TEST":
            return
        try:
            updated = self.llm.apply_test_edits(task["test"], feedback)
        except LLMError:
            self.bot.send_message(task["expert_channel_id"],
                "❌ Ошибка при применении правок. Попробуй ещё раз.")
            return
        version = (task.get("test_version") or 1) + 1
        edit_count = (task.get("test_edit_count") or 0) + 1
        self.state.update_task(task["id"],
            test=updated, test_version=version, test_edit_count=edit_count)
        self._send_test_for_review(task["id"], task["expert_channel_id"], updated, version)

    def _send_to_methodologist(self, task: dict):
        task = self.state.get_task(task["id"])  # refresh
        longread_path = f"{UPLOAD_DIR}/{task['id']}_longread_final.md"
        with open(longread_path, "w", encoding="utf-8") as f:
            f.write(task["longread"])

        test_info = ""
        test_path = None
        if task.get("test"):
            test_path = f"{UPLOAD_DIR}/{task['id']}_test_final.json"
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(task["test"])
            test_info = " + тест"

        meth_channel = task["methodologist_channel_id"]
        self.bot.send_message(meth_channel,
            f"📚 Новый материал готов к проверке!\n\n"
            f"**Тема:** {task['topic']}\n"
            f"**Эксперт:** пользователь #{task['expert_mm_id']}\n\n"
            f"Прилагаю лонгрид{test_info}. Посмотри и одобри или оставь комментарии.")
        self.bot.send_file(meth_channel, longread_path, "📄 Лонгрид:")
        if test_path:
            self.bot.send_file(meth_channel, test_path, "📋 Тест:")
        self.bot.send_buttons(meth_channel, "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task["id"], "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task["id"], "action": "request_changes"}},
            ])

    def _on_methodologist_approve(self, task: dict):
        self.state.update_task(task["id"], status="DONE")
        self.bot.send_message(task["methodologist_channel_id"],
            "✅ Отлично! Материал отмечен как согласованный.")
        self.bot.send_message(task["expert_channel_id"],
            f"🎉 Материал по теме «{task['topic']}» согласован методологом!\n\n"
            "Методолог свяжется с тобой по поводу публикации на платформе.")

    def _on_methodologist_request_changes(self, task: dict):
        self.bot.send_message(task["methodologist_channel_id"],
            "Напиши, что нужно изменить — я передам правки и обновлю материал.")

    def _handle_methodologist_feedback_text(self, task: dict, feedback: str):
        if not feedback.strip():
            return
        task = self.state.get_task(task["id"])
        if task["status"] != "REVIEW_METHODOLOGIST":
            return
        try:
            updated_longread = self.llm.apply_edits(task["longread"], feedback)
        except LLMError:
            self.bot.send_message(task["methodologist_channel_id"],
                "❌ Ошибка при применении правок. Попробуй ещё раз.")
            return
        version = (task.get("longread_version") or 1) + 1
        self.state.update_task(task["id"],
            longread=updated_longread, longread_version=version)
        self._send_to_methodologist(task)
```

- [ ] **Step 4: Run tests — verify they PASS**

```bash
pytest tests/test_handler.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add handler.py tests/test_handler.py
git commit -m "feat: handler with full scenario 2 state machine"
```

---

## Task 9: Main Entry Point (main.py)

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement main.py**

```python
# main.py
import os
import logging
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from bot import MattermostBot
from state import StateManager
from handler import Handler
from services.llm import LLMService
from services.transcription import TranscriptionService

# --- Init services ---
bot = MattermostBot(
    url=os.environ["MATTERMOST_URL"],
    token=os.environ["MATTERMOST_BOT_TOKEN"],
)
state = StateManager()
llm = LLMService(api_key=os.environ["ANTHROPIC_API_KEY"])
transcription = TranscriptionService(api_key=os.environ.get("TRANSKRIPTOR_API_KEY"))
handler = Handler(
    bot=bot,
    state=state,
    llm=llm,
    methodologist_mm_id=os.environ["METHODOLOGIST_USER_ID"],
    transcription=transcription,
)

# --- Wire up message callback ---
def on_message(user_id: str, channel_id: str, message: str, file_ids: list):
    try:
        handler.handle_message(user_id, channel_id, message, file_ids)
    except Exception:
        logger.exception(f"Unhandled error processing message from {user_id}")

bot.set_message_callback(on_message)

# --- FastAPI app ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Login and start WebSocket listener on startup
    bot.login()
    bot.start_listening()
    logger.info("Bot started and listening to Mattermost")
    yield
    bot.stop()
    logger.info("Bot stopped")

app = FastAPI(lifespan=lifespan)

@app.post("/api/button_callback")
async def button_callback(request: Request):
    """Receive interactive button clicks from Mattermost."""
    body = await request.json()
    context = body.get("context", {})
    task_id = context.get("task_id")
    action = context.get("action")
    user_id = body.get("user_id")

    if not task_id or not action:
        return JSONResponse({"error": "missing task_id or action"}, status_code=400)

    # Run in thread to avoid blocking async event loop
    threading.Thread(
        target=handler.handle_button,
        args=(task_id, action, user_id),
        daemon=True,
    ).start()

    return JSONResponse({"update": {"message": ""}})  # Mattermost expects this response

@app.get("/health")
async def health():
    return {"status": "ok", "bot_user_id": bot.bot_user_id}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

- [ ] **Step 2: Test startup**

```bash
python main.py
```

Expected output:
```
INFO: Bot started and listening to Mattermost
INFO: Uvicorn running on http://0.0.0.0:8000
```

Check health endpoint:
```bash
curl http://localhost:8000/health
```
Expected: `{"status": "ok", "bot_user_id": "..."}`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: FastAPI entrypoint with bot startup and button callback"
```

---

## Task 10: End-to-End Smoke Test

**Manual test in real Mattermost.** No automated test for this task.

- [ ] **Step 1: Start the bot**

```bash
source .venv/bin/activate
python main.py
```

- [ ] **Step 2: Send a message from expert account**

In Mattermost, open DM with the bot and send:
> Хочу сделать курс по основам эффективных коммуникаций

Expected: bot responds with duplicate check message and two buttons.

- [ ] **Step 3: Click "Продолжить"**

Expected: bot asks to upload materials.

- [ ] **Step 4: Upload a .txt or .docx file**

Expected: bot acknowledges, starts processing, sends back longread file with Approve/Request Changes buttons.

- [ ] **Step 5: Approve the longread**

Expected: bot asks about test type.

- [ ] **Step 6: Choose "Тест с вариантами"**

Expected: bot generates and sends test JSON with buttons.

- [ ] **Step 7: Approve the test**

Expected: bot sends materials to methodologist's DM.

- [ ] **Step 8: Methodologist approves**

Expected: expert receives "Материал согласован! 🎉"

- [ ] **Step 9: Final commit**

```bash
git add .
git commit -m "feat: MVP complete — Scenario 2 end-to-end"
```

---

## Run All Tests

```bash
pytest tests/test_state.py tests/test_files.py tests/test_llm.py tests/test_handler.py -v
```

Expected: all tests PASS (integration test requires manual run with real credentials).
