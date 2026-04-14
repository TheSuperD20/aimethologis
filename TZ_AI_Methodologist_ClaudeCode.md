# ТЗ для Claude Code: ИИ-Методолог — Mattermost-бот

## Что это за проект

Mattermost-бот «ИИ-Методолог», который автоматизирует создание обучающих курсов в компании. Бот живёт в корпоративном мессенджере Mattermost, общается с методологом и экспертами, собирает знания, транскрибирует видео, генерирует обучающие лонгриды и тесты через Claude API, согласовывает их с участниками и публикует на корпоративной LMS-платформе «Кампус».

---

## Стек технологий

- **Язык**: Python 3.11+
- **Фреймворк**: FastAPI + uvicorn (HTTP-сервер для вебхуков Mattermost)
- **Async**: asyncio + httpx (асинхронные HTTP-запросы)
- **База данных**: SQLite (для локальной разработки) через SQLAlchemy async + aiosqlite
- **LLM**: Anthropic Claude API (модель claude-sonnet-4-20250514)
- **Транскрибация**: Transkriptor API (https://api.tor.app)
- **Mattermost**: mattermostdriver (Python-клиент) + WebSocket для real-time
- **Кампус LMS**: REST API (документация будет приложена отдельно)
- **Право ТВ** (видеохостинг): mock-заглушка (API недоступен)
- **Контейнеризация**: Docker + docker-compose
- **Управление зависимостями**: Poetry или pip + requirements.txt

---

## Структура проекта

```
ai-methodologist/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example                 # Шаблон переменных окружения
├── alembic/                     # Миграции БД
│   └── versions/
├── alembic.ini
├── src/
│   ├── __init__.py
│   ├── main.py                  # Точка входа FastAPI
│   ├── config.py                # Загрузка .env, настройки
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── mattermost_client.py # Подключение к Mattermost, отправка сообщений
│   │   ├── event_handler.py     # Обработка входящих сообщений (WebSocket)
│   │   └── commands.py          # Парсинг команд пользователя
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── engine.py            # Стейт-машина, управление переходами
│   │   ├── scenarios.py         # Логика сценариев 1 и 2
│   │   └── reminders.py         # Таймауты и напоминания (фоновые задачи)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm.py               # Обёртка над Claude API (генерация лонгридов, тестов)
│   │   ├── transcription.py     # Обёртка над Transkriptor API
│   │   ├── campus.py            # Клиент Campus API (публикация, поиск дублей)
│   │   ├── pravotv.py           # Mock-заглушка Право ТВ
│   │   └── content_processor.py # Извлечение текста из DOCX/PDF/PPTX
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py          # SQLAlchemy engine, session
│   │   ├── task.py              # Модель LearningTask
│   │   ├── material.py          # Модель Material
│   │   ├── content.py           # Модель Content (лонгриды, тесты)
│   │   └── dialog.py            # Модель DialogHistory
│   ├── prompts/
│   │   ├── longread.py          # Промпты для генерации лонгридов
│   │   ├── test.py              # Промпты для генерации тестов
│   │   └── system.py            # Системный промпт бота
│   └── utils/
│       ├── __init__.py
│       └── file_helpers.py      # Работа с файлами (скачивание, определение типа)
├── tests/
│   ├── test_orchestrator.py
│   ├── test_llm.py
│   ├── test_transcription.py
│   └── test_commands.py
└── data/
    └── uploads/                 # Загруженные файлы (локально, .gitignore)
```

---

## Переменные окружения (.env.example)

```env
# Mattermost
MATTERMOST_URL=http://localhost:8065
MATTERMOST_BOT_TOKEN=your_bot_token
MATTERMOST_BOT_USERNAME=ai-methodologist

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# Transkriptor
TRANSKRIPTOR_API_KEY=your_transkriptor_api_key

# Campus LMS
CAMPUS_API_URL=https://campus.company.ru/api/v1
CAMPUS_API_KEY=your_campus_api_key

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db

# Настройки бота
REMINDER_TIMEOUT_HOURS=24
MAX_REMINDER_COUNT=3
MAX_EDIT_ITERATIONS=5

# ID методолога в Mattermost (кто является администратором бота)
METHODOLOGIST_USER_ID=mattermost_user_id_here
```

---

## Модель данных

### Таблица: learning_tasks

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID, PK | Уникальный идентификатор |
| scenario | ENUM("methodologist_initiated", "expert_initiated") | Тип сценария |
| status | VARCHAR(50) | Текущий статус (см. стейт-машину ниже) |
| topic | VARCHAR(500) | Тема курса |
| methodologist_mm_id | VARCHAR(100) | Mattermost user ID методолога |
| expert_mm_id | VARCHAR(100) | Mattermost user ID эксперта |
| channel_methodologist | VARCHAR(100) | ID DM-канала бот↔методолог |
| channel_expert | VARCHAR(100) | ID DM-канала бот↔эксперт |
| iteration_count | INT, default 0 | Счётчик итераций правок |
| needs_test | BOOLEAN, nullable | Нужна ли проверка знаний (null = ещё не спрашивали) |
| test_type | VARCHAR(50), nullable | Тип теста: "quiz" / "case" / "open_questions" |
| campus_course_id | VARCHAR(100), nullable | ID курса на Кампусе после публикации |
| campus_url | VARCHAR(500), nullable | Ссылка на опубликованный курс |
| last_action_at | TIMESTAMP | Время последнего действия (для таймаутов) |
| created_at | TIMESTAMP | Дата создания |
| updated_at | TIMESTAMP | Дата обновления |

### Таблица: materials

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID, PK | Уникальный идентификатор |
| task_id | UUID, FK → learning_tasks | Привязка к задаче |
| type | ENUM("video_file", "video_link", "document", "presentation", "audio") | Тип материала |
| original_filename | VARCHAR(500) | Исходное имя файла |
| source_url | VARCHAR(1000), nullable | Ссылка (для видео по ссылке) |
| file_path | VARCHAR(500), nullable | Путь к файлу в локальном хранилище |
| transcript | TEXT, nullable | Результат транскрибации |
| transkriptor_order_id | VARCHAR(100), nullable | ID заказа в Transkriptor (для polling) |
| status | ENUM("uploaded", "processing", "transcribed", "error") | Статус обработки |
| error_message | TEXT, nullable | Сообщение об ошибке |
| uploaded_at | TIMESTAMP | Дата загрузки |

### Таблица: contents

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID, PK | Уникальный идентификатор |
| task_id | UUID, FK → learning_tasks | Привязка к задаче |
| type | ENUM("longread", "test", "case") | Тип контента |
| version | INT, default 1 | Версия (инкремент при правках) |
| body | TEXT | Тело (Markdown для лонгрида, JSON для теста) |
| status | ENUM("draft", "approved_methodologist", "approved_expert", "published") | Статус |
| created_at | TIMESTAMP | Дата создания версии |

### Таблица: dialog_history

| Поле | Тип | Описание |
|------|-----|----------|
| id | UUID, PK | Уникальный идентификатор |
| task_id | UUID, FK → learning_tasks | Привязка к задаче |
| sender | ENUM("bot", "methodologist", "expert") | Отправитель |
| message | TEXT | Текст сообщения |
| mm_post_id | VARCHAR(100), nullable | ID поста в Mattermost |
| timestamp | TIMESTAMP | Время |

---

## Стейт-машина

### Сценарий 1: Методолог инициирует сбор знаний

```
INIT
  │ Бот отправил запрос эксперту
  ▼
WAITING_EXPERT_MATERIALS
  │ Эксперт загрузил файлы/ссылки
  ▼
PROCESSING
  │ Транскрибация + генерация лонгрида
  ▼
REVIEW_METHODOLOGIST ◄────────────────────┐
  │                                        │
  ├─ Методолог одобрил ──► ASK_TEST        │
  │                           │             │
  │                ┌──────────┤             │
  │                │          │             │
  │            Да  ▼      Нет ▼             │
  │     GENERATING_TEST   REVIEW_EXPERT     │
  │           │              │              │
  │           ▼              │              │
  │     REVIEW_TEST_METH     │              │
  │       │       │          │              │
  │   Одобрил  Правки──►GENERATING_TEST    │
  │       │                  │              │
  │       ▼                  │              │
  │   REVIEW_EXPERT ◄────────┘              │
  │       │       │                         │
  │   Ок  │   Правки────────────────────────┘
  │       ▼
  │   PUBLISHING
  │       │ Курс опубликован на Кампусе
  │       ▼
  │   AWAITING_ACCESS
  │       │ Методолог подтвердил открытие доступов
  │       ▼
  └── COMPLETED (бот уведомляет эксперта ссылкой)
  
  Методолог вернул правки ──► PROCESSING (iteration_count += 1)
```

### Сценарий 2: Эксперт инициирует создание курса

```
EXPERT_INIT
  │ Бот проверяет дубли на Кампусе
  ▼
CHECKING_DUPLICATES
  │ Результат показан эксперту
  ├─ Дубль найден, эксперт отказался ──► CANCELLED
  ├─ Нет дублей / эксперт подтвердил ──▼
  ▼
WAITING_EXPERT_MATERIALS
  │ Эксперт загрузил материалы
  ▼
PROCESSING
  │ Транскрибация + генерация лонгрида
  ▼
REVIEW_EXPERT ◄───────────────────────────┐
  │                                        │
  ├─ Эксперт одобрил ──► ASK_TEST         │
  │                          │              │
  │               ┌──────────┤              │
  │               │          │              │
  │           Да  ▼      Нет ▼              │
  │    GENERATING_TEST  REVIEW_METHODOLOGIST│
  │          │              │               │
  │          ▼              │               │
  │    REVIEW_TEST_EXPERT   │               │
  │      │       │          │               │
  │  Одобрил  Правки──►GENERATING_TEST     │
  │      │                  │               │
  │      ▼                  │               │
  │  REVIEW_METHODOLOGIST ◄─┘               │
  │      │       │                          │
  │  Одобрил  Правки────────────────────────┘
  │      ▼
  │  PUBLISHING
  │      │ Курс опубликован
  │      ▼
  │  AWAITING_ACCESS
  │      │ Методолог подтвердил
  │      ▼
  └── COMPLETED (бот уведомляет эксперта ссылкой)
```

### Общие статусы (оба сценария)

- **PAUSED** — эксперт или методолог не отвечают после 3 напоминаний (72ч)
- **CANCELLED** — методолог отменил задачу командой `/cancel {task_id}`
- **ERROR** — критическая ошибка (сбой API, невосстановимая ошибка)

---

## Реализация по файлам

### 1. `src/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Mattermost
    mattermost_url: str
    mattermost_bot_token: str
    mattermost_bot_username: str = "ai-methodologist"
    
    # Anthropic
    anthropic_api_key: str
    
    # Transkriptor
    transkriptor_api_key: str
    
    # Campus
    campus_api_url: str
    campus_api_key: str
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    
    # Bot settings
    reminder_timeout_hours: int = 24
    max_reminder_count: int = 3
    max_edit_iterations: int = 5
    methodologist_user_id: str = ""
    
    class Config:
        env_file = ".env"
```

### 2. `src/bot/mattermost_client.py`

Реализовать класс `MattermostClient`:

- Подключение через `mattermostdriver` (asyncio-совместимо)
- WebSocket-подписка на события новых сообщений
- Методы:
  - `send_message(channel_id: str, message: str) -> str` — отправить текст, вернуть post_id
  - `send_message_with_buttons(channel_id: str, message: str, buttons: list[dict]) -> str` — Interactive Message с кнопками. Каждая кнопка = `{"name": str, "integration": {"url": str, "context": dict}}`
  - `send_file(channel_id: str, file_path: str, message: str) -> str` — отправить файл с сопроводительным текстом
  - `get_direct_channel(user_id: str) -> str` — получить или создать DM-канал бот↔пользователь
  - `download_file(file_id: str, save_path: str)` — скачать файл из Mattermost
  - `get_user_info(user_id: str) -> dict` — получить имя/username пользователя

**Важно**: Mattermost Interactive Messages отправляют POST-запрос на `integration.url` при нажатии кнопки. FastAPI должен слушать этот endpoint.

### 3. `src/bot/event_handler.py`

Обработчик WebSocket-событий от Mattermost:

- Фильтровать только `posted` события (новые сообщения)
- Игнорировать сообщения от самого бота
- Определить, кто пишет (методолог или эксперт) по `user_id`
- Определить, есть ли активная задача с этим пользователем
- Передать в `commands.py` для парсинга команды
- Передать в `orchestrator/engine.py` для обработки в контексте текущего состояния

### 4. `src/bot/commands.py`

Парсинг входящих сообщений. Бот должен понимать:

**От методолога:**
- Свободный текст вида «Сходи к @username и забери материалы по теме X» → извлечь username эксперта и тему. Использовать Claude API для извлечения intent + entities из свободного текста.
- `/cancel {task_id}` — отменить задачу
- `/status` — показать список активных задач
- `/status {task_id}` — показать детали задачи

**От эксперта:**
- Свободный текст вида «У меня есть материал по теме X, хочу сделать курс» → определить intent = создание курса, извлечь тему
- Загрузка файлов (вложения в сообщении Mattermost)
- Отправка ссылок на видео (URL в тексте)
- Текстовые ответы: «всё ок», «нужно поправить вот это» → определить approve/reject

**От обоих (в контексте ревью):**
- Нажатие на кнопку «Одобрить» / «Нужны правки» → приходит через Interactive Message callback
- Текст с правками после нажатия «Нужны правки»

Для определения intent из свободного текста использовать Claude API с коротким промптом:

```python
INTENT_PROMPT = """Определи намерение пользователя из сообщения в корпоративном мессенджере.
Контекст: пользователь общается с ботом для создания обучающих курсов.

Возможные intent:
- "collect_knowledge" — методолог просит собрать материалы у эксперта (извлечь: expert_username, topic)
- "create_course" — эксперт хочет создать курс (извлечь: topic)
- "approve" — одобрение материала
- "request_changes" — запрос на правки (извлечь: feedback — текст с правками)
- "upload_materials" — загрузка материалов
- "send_link" — отправка ссылки на видео (извлечь: url)
- "cancel" — отмена
- "status" — запрос статуса
- "confirm_access" — подтверждение открытия доступов
- "unknown" — не удалось определить

Ответь ТОЛЬКО валидным JSON:
{"intent": "...", "entities": {...}}

Сообщение: {message}"""
```

### 5. `src/orchestrator/engine.py`

Центральный модуль — стейт-машина. Реализовать класс `Orchestrator`:

```python
class Orchestrator:
    async def handle_event(self, task: LearningTask, event: str, data: dict) -> None:
        """
        Главный метод. Принимает задачу, тип события и данные.
        Определяет текущий статус, выполняет действие, переводит в новый статус.
        
        event — один из:
        - "methodologist_command" (новая команда от методолога)
        - "expert_init" (эксперт инициировал курс)
        - "materials_uploaded" (эксперт загрузил материалы)
        - "link_sent" (эксперт отправил ссылку)
        - "transcription_complete" (транскрибация завершена)
        - "content_generated" (лонгрид/тест сгенерирован)
        - "approved" (одобрение от методолога/эксперта)
        - "changes_requested" (правки от методолога/эксперта)
        - "test_decision" (да/нет на вопрос о тесте)
        - "test_type_selected" (выбор типа теста)
        - "publish_complete" (публикация завершена)
        - "access_confirmed" (методолог подтвердил открытие доступов)
        - "cancel" (отмена)
        """
        handler = self._get_handler(task.status, event)
        if handler:
            await handler(task, data)
        else:
            # Неожиданное сочетание статуса и события — логировать и сообщить пользователю
            pass
    
    async def _handle_init_materials_uploaded(self, task, data):
        """Пример: в статусе WAITING_EXPERT_MATERIALS получили материалы"""
        # 1. Сохранить материалы в БД
        # 2. Если есть видео — отправить на транскрибацию
        # 3. Если только текст — перейти к обработке
        # 4. Обновить статус → PROCESSING
        # 5. Запустить генерацию лонгрида
        pass
```

**Правила переходов** — реализовать как dict-маппинг `(status, event) → handler_function`. Каждый handler:
1. Выполняет бизнес-логику
2. Обновляет статус задачи в БД
3. Отправляет сообщения пользователям через `MattermostClient`
4. Обновляет `last_action_at` (для таймаутов)

### 6. `src/orchestrator/reminders.py`

Фоновая задача (asyncio Task), которая:
- Каждые 30 минут проверяет все задачи со статусами `WAITING_*`, `REVIEW_*`
- Если `datetime.now() - task.last_action_at > REMINDER_TIMEOUT_HOURS` и не превышен лимит напоминаний → отправить напоминание
- Если лимит напоминаний исчерпан → перевести в `PAUSED`, уведомить методолога
- Реализовать как `asyncio.create_task` при старте приложения

### 7. `src/services/llm.py`

Обёртка над Anthropic Claude API. Использовать библиотеку `anthropic`.

```python
import anthropic

class LLMService:
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
    
    async def parse_intent(self, message: str, context: dict) -> dict:
        """Определить intent пользователя. Вернуть {"intent": ..., "entities": ...}"""
        pass
    
    async def generate_longread(self, transcript: str, topic: str, style_references: str = "") -> str:
        """
        Сгенерировать лонгрид на основе транскрипта.
        Вернуть Markdown-текст.
        """
        pass
    
    async def apply_edits(self, current_text: str, feedback: str) -> str:
        """Применить правки к лонгриду на основе комментариев."""
        pass
    
    async def generate_test(self, longread: str, test_type: str) -> str:
        """
        Сгенерировать тест.
        test_type: "quiz" | "case" | "open_questions"
        Вернуть JSON.
        """
        pass
    
    async def apply_test_edits(self, current_test: str, feedback: str) -> str:
        """Применить правки к тесту."""
        pass
```

### 8. `src/services/transcription.py`

Обёртка над Transkriptor API. Base URL: `https://api.tor.app`.

```python
class TranskriptorService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.tor.app/developer"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
    
    async def transcribe_local_file(self, file_path: str, language: str = "ru") -> str:
        """
        Транскрибация локального файла.
        Шаги:
        1. POST /transcription/local_file/get_upload_url — получить upload_url и public_url
        2. PUT upload_url — загрузить файл
        3. POST /transcription/initiate — начать транскрибацию с public_url
        4. Вернуть order_id для дальнейшего polling
        """
        pass
    
    async def transcribe_url(self, url: str, language: str = "ru") -> str:
        """
        Транскрибация по ссылке (YouTube, Google Drive, и т.д.)
        POST /transcription/initiate с URL
        Вернуть order_id
        """
        pass
    
    async def get_transcription_status(self, order_id: str) -> dict:
        """
        Проверить статус транскрибации.
        GET /files/{order_id}/content
        Вернуть {"status": "processing"|"completed"|"error", "text": ...}
        """
        pass
    
    async def get_transcription_text(self, order_id: str) -> str:
        """
        Получить текст транскрибации.
        GET /files/{order_id}/content
        Вернуть plain text.
        """
        pass
    
    async def wait_for_transcription(self, order_id: str, poll_interval: int = 30, timeout: int = 3600) -> str:
        """
        Polling до завершения транскрибации.
        Каждые poll_interval секунд проверять статус.
        Если timeout — raise TimeoutError.
        Вернуть текст.
        """
        pass
```

**Важно**: Transkriptor API может обрабатывать файл долго (минуты). Реализовать polling с `asyncio.sleep`. Не блокировать основной event loop.

### 9. `src/services/campus.py`

Клиент Campus API. **Документация Кампуса будет приложена отдельным файлом.** Пока реализовать интерфейс:

```python
class CampusService:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
    
    async def search_courses(self, query: str) -> list[dict]:
        """
        Поиск курсов по ключевым словам (для проверки дублей).
        GET /courses?search={query}
        Вернуть [{id, title, description, url}, ...]
        """
        pass
    
    async def create_course(self, title: str, description: str) -> dict:
        """
        Создать курс.
        POST /courses
        Вернуть {id, url}
        """
        pass
    
    async def upload_content(self, course_id: str, content_type: str, body: str) -> bool:
        """
        Загрузить контент в курс.
        POST /courses/{course_id}/content
        content_type: "longread" | "test"
        body: Markdown (лонгрид) или JSON (тест)
        """
        pass
    
    async def publish_course(self, course_id: str) -> dict:
        """
        Опубликовать курс.
        POST /courses/{course_id}/publish
        Вернуть {url}
        """
        pass
```

**Когда документация Кампуса будет приложена**: заменить заглушки реальными HTTP-запросами с правильными endpoint-ами, заголовками и форматом данных.

### 10. `src/services/pravotv.py`

Mock-заглушка для Право ТВ:

```python
class PravoTVService:
    """
    Заглушка. API Право ТВ недоступен.
    Когда API будет доступен — заменить реальной реализацией.
    """
    async def download_video(self, url: str, save_path: str) -> str:
        """
        Пока: если URL содержит 'pravotv' — вернуть ошибку с понятным сообщением.
        В будущем: скачать видео по API Право ТВ.
        """
        raise NotImplementedError(
            "Интеграция с Право ТВ пока недоступна. "
            "Попросите эксперта загрузить видеофайл напрямую."
        )
```

### 11. `src/services/content_processor.py`

Извлечение текста из документов:

```python
class ContentProcessor:
    async def extract_text(self, file_path: str) -> str:
        """
        Определить тип файла по расширению и извлечь текст.
        Поддерживаемые форматы:
        - .docx → python-docx
        - .pdf → PyPDF2 или pdfplumber
        - .pptx → python-pptx (текст со слайдов + заметки)
        - .txt → прямое чтение
        Вернуть plain text.
        """
        pass
    
    def detect_file_type(self, filename: str) -> str:
        """Вернуть тип: 'document', 'presentation', 'video', 'audio', 'unknown'"""
        pass
    
    def is_video_url(self, text: str) -> str | None:
        """Если текст содержит URL на видео (youtube, zoom, pravotv) — вернуть URL, иначе None"""
        pass
```

### 12. `src/prompts/longread.py`

```python
LONGREAD_SYSTEM_PROMPT = """Ты — ИИ-методолог, который создаёт обучающие материалы для сотрудников компании.

Твоя задача — написать лонгрид (обучающую статью) на основе предоставленного материала.

Требования к стилю:
- Дружелюбный, без канцеляризмов
- Понятный для сотрудников без специальных знаний по теме
- С примерами из практики, если они есть в исходном материале
- Живой язык, как будто объясняешь коллеге

Структура лонгрида:
1. Заголовок (привлекающий внимание)
2. Введение (1-2 абзаца: зачем это нужно, почему важно)
3. Основная часть с подзаголовками (разбить на логические блоки)
4. Ключевые выводы (3-5 пунктов — что запомнить)

Объём: 3000-10000 символов в зависимости от объёма исходного материала.
Формат: Markdown."""

LONGREAD_USER_PROMPT = """Тема: {topic}

Исходный материал (транскрипт/текст):
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

Внеси правки в лонгрид согласно комментариям. Верни обновлённый текст целиком в Markdown."""
```

### 13. `src/prompts/test.py`

```python
QUIZ_PROMPT = """На основе этого обучающего лонгрида создай тест для проверки знаний.

Лонгрид:
---
{longread}
---

Создай {num_questions} вопросов с 4 вариантами ответа (один правильный).

Ответь СТРОГО в JSON формате:
{{
  "questions": [
    {{
      "question": "Текст вопроса?",
      "options": ["Вариант A", "Вариант B", "Вариант C", "Вариант D"],
      "correct_index": 0,
      "explanation": "Почему это правильный ответ"
    }}
  ]
}}"""

CASE_PROMPT = """На основе этого обучающего лонгрида создай кейс-задание.

Лонгрид:
---
{longread}
---

Создай кейс: опиши реалистичную рабочую ситуацию и задай 3-5 вопросов для анализа.

Ответь СТРОГО в JSON формате:
{{
  "case_description": "Описание ситуации...",
  "questions": [
    {{
      "question": "Вопрос для анализа?",
      "hint": "Подсказка, на что обратить внимание"
    }}
  ]
}}"""
```

---

## Логика взаимодействия: подробные сценарии

### Сценарий 1: Методолог → Бот → Эксперт

**Шаг 1: Методолог пишет боту**

Методолог отправляет сообщение в DM боту, например:
> Сходи к @ivan.petrov и забери материалы по вебинару «Новые стандарты клиентского сервиса»

Бот:
1. Парсит intent через Claude → `{"intent": "collect_knowledge", "entities": {"expert_username": "ivan.petrov", "topic": "Новые стандарты клиентского сервиса"}}`
2. Находит `user_id` по username через Mattermost API
3. Создаёт `LearningTask(scenario="methodologist_initiated", status="INIT", topic=..., expert_mm_id=..., methodologist_mm_id=...)`
4. Получает/создаёт DM-каналы бот↔методолог и бот↔эксперт
5. Отвечает методологу: «Принял! Напишу @ivan.petrov и попрошу материалы по теме «Новые стандарты клиентского сервиса». Сообщу, когда получу ответ.»
6. Пишет эксперту: «Привет, Иван! Методолог просит материалы по вебинару «Новые стандарты клиентского сервиса». Пожалуйста, загрузи файлы или отправь ссылку на запись. Принимаю: видео (файл или ссылка), документы (DOCX, PDF), презентации (PPTX).»
7. Обновляет статус → `WAITING_EXPERT_MATERIALS`

**Шаг 2: Эксперт загружает материалы**

Эксперт может:
- Прикрепить файл(ы) к сообщению в Mattermost
- Отправить ссылку на видео (Zoom, YouTube, Право ТВ)
- Отправить текстовое сообщение с описанием

Бот:
1. Скачивает файлы через Mattermost API → сохраняет в `data/uploads/{task_id}/`
2. Создаёт записи `Material` для каждого файла/ссылки
3. Отвечает эксперту: «Спасибо! Получил {N} файл(ов). Обрабатываю, это может занять несколько минут.»
4. Для видео → отправляет на транскрибацию через Transkriptor API
5. Для документов → извлекает текст через `ContentProcessor`
6. Обновляет статус → `PROCESSING`
7. Когда вся транскрибация завершена → объединяет тексты всех материалов
8. Генерирует лонгрид через Claude API
9. Сохраняет лонгрид как `Content(type="longread", version=1, status="draft")`
10. Отправляет лонгрид методологу как файл (Markdown) с кнопками:
    - ✅ Одобрить
    - ✏️ Нужны правки
11. Уведомляет методолога: «Получил материалы от @ivan.petrov (видео 47 мин). Транскрибация завершена, лонгрид сгенерирован. Посмотри черновик.»
12. Обновляет статус → `REVIEW_METHODOLOGIST`

**Шаг 3: Методолог ревьюит**

Если нажал «Одобрить» → переход к шагу 4.

Если нажал «Нужны правки»:
1. Бот отвечает: «Напиши, что нужно изменить.»
2. Методолог пишет комментарии текстом
3. Бот передаёт правки в Claude API → получает обновлённый лонгрид
4. `iteration_count += 1`. Если `>= max_edit_iterations` → предложить встречу.
5. Сохраняет новую версию `Content(version += 1)`
6. Отправляет обновлённый лонгрид с теми же кнопками
7. Цикл повторяется

**Шаг 4: Вопрос о тесте**

Бот спрашивает методолога:
> Нужна ли проверка знаний к этому материалу?
> [Кнопки: Тест с вариантами | Кейс-задание | Открытые вопросы | Не нужна]

Если «Не нужна» → переход к шагу 6 (REVIEW_EXPERT).

Если выбран тип теста:
1. Бот генерирует тест через Claude API
2. Отправляет методологу с кнопками [Одобрить | Нужны правки]
3. Цикл правок как с лонгридом
4. После одобрения → переход к шагу 6

**Шаг 5 (пропущен, если тест не нужен)**

**Шаг 6: Ревью экспертом**

Бот пишет эксперту:
> Мы подготовили обучающий материал на основе твоих данных. Посмотри, пожалуйста, всё ли корректно по смыслу?
> [прикреплённый файл: лонгрид + тест]
> [Кнопки: Всё верно | Есть замечания]

Если «Есть замечания»:
1. Эксперт пишет правки
2. Бот применяет правки через Claude API
3. Отправляет обратно методологу (возврат в REVIEW_METHODOLOGIST)

Если «Всё верно» → переход к шагу 7.

**Шаг 7: Публикация**

Бот:
1. Создаёт курс на Кампусе через API
2. Загружает лонгрид и тест
3. Публикует курс
4. Сохраняет `campus_course_id` и `campus_url`
5. Пишет методологу: «Материал «Новые стандарты клиентского сервиса» опубликован на Кампусе: {url}. Проверь и открой доступы сотрудникам. Напиши мне «доступ открыт», когда будет готово.»
6. Статус → `AWAITING_ACCESS`

**Шаг 8: Открытие доступов**

Методолог проверяет курс на Кампусе, открывает доступы вручную, пишет боту «доступ открыт».

Бот:
1. Пишет эксперту: «Твой материал «Новые стандарты клиентского сервиса» опубликован на Кампусе и доступен сотрудникам! Вот ссылка: {url}. Спасибо за вклад! 🎓»
2. Статус → `COMPLETED`

---

### Сценарий 2: Эксперт → Бот → Методолог

Отличия от Сценария 1:
1. Эксперт пишет боту первый: «У меня есть материал по теме X, хочу сделать курс»
2. Бот **сначала проверяет дубли** на Кампусе → показывает эксперту похожие курсы
3. Порядок ревью **обратный**: сначала эксперт, потом методолог
4. Бот уведомляет методолога **после** одобрения экспертом (а не наоборот)

Реализация аналогична Сценарию 1, но с другим порядком переходов (см. стейт-машину выше).

---

## FastAPI endpoints

```python
# main.py

@app.on_event("startup")
async def startup():
    # 1. Инициализировать БД
    # 2. Подключиться к Mattermost WebSocket
    # 3. Запустить фоновую задачу напоминаний

@app.post("/api/v1/mattermost/interactive")
async def mattermost_interactive(request: Request):
    """
    Callback для Interactive Messages (кнопки в Mattermost).
    Mattermost присылает POST с context, который мы задали при создании кнопки.
    """
    pass

@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}

@app.get("/api/v1/tasks")
async def list_tasks():
    """Список всех задач (для отладки)"""
    pass

@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """Детали задачи (для отладки)"""
    pass
```

---

## Docker

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: "3.8"

services:
  bot:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    
  # Для локальной разработки: Mattermost
  mattermost:
    image: mattermost/mattermost-preview:latest
    ports:
      - "8065:8065"
    volumes:
      - mattermost-data:/mm/mattermost-data

volumes:
  mattermost-data:
```

---

## Зависимости (requirements.txt)

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
anthropic>=0.40.0
mattermostdriver>=7.3.2
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
alembic>=1.13.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-docx>=1.1.0
PyPDF2>=3.0.0
python-pptx>=0.6.23
python-multipart>=0.0.9
```

---

## Обработка ошибок

Каждый внешний вызов (Claude API, Transkriptor API, Campus API, Mattermost API) оборачивать в try/except с:
1. **Retry**: до 3 попыток с exponential backoff (1с, 5с, 15с) для 5xx и таймаутов
2. **Logging**: логировать все ошибки в structured JSON (loguru или structlog)
3. **User notification**: при фатальной ошибке — отправить понятное сообщение пользователю

| Ошибка | Поведение |
|--------|-----------|
| Transkriptor 4xx/5xx | Retry 3 раза. При неудаче → сообщить эксперту: «Не удалось обработать файл. Попробуй другой формат или загрузи заново.» |
| Claude API таймаут | Retry 3 раза. При неудаче → сообщить методологу, задача в ERROR |
| Campus API недоступен | Retry 3 раза с интервалом 5 мин. При неудаче → PAUSED, уведомить методолога |
| Mattermost disconnect | Auto-reconnect WebSocket с backoff |
| Файл неподдерживаемого формата | Сообщить эксперту список поддерживаемых форматов |
| Пустой файл / повреждён | Сообщить эксперту: «Файл пустой или повреждён, загрузи другой» |
| Право ТВ ссылка | Сообщить: «Интеграция с Право ТВ пока недоступна. Загрузи видеофайл напрямую.» |

---

## Порядок реализации (для Claude Code)

Рекомендуемый порядок. Каждый шаг — рабочий, тестируемый инкремент.

### Фаза 1: Скелет
1. Инициализировать проект: структура папок, requirements.txt, .env.example
2. `config.py` — загрузка настроек
3. `models/` — все SQLAlchemy модели + Alembic миграция
4. `main.py` — FastAPI с health endpoint + инициализация БД

### Фаза 2: Mattermost
5. `mattermost_client.py` — подключение, отправка сообщений, WebSocket
6. `event_handler.py` — получение и роутинг сообщений
7. Протестировать: бот отвечает на сообщения «echo»

### Фаза 3: Сценарий 1 (happy path)
8. `commands.py` — парсинг intent через Claude API
9. `llm.py` — генерация лонгрида
10. `orchestrator/engine.py` — стейт-машина для Сценария 1
11. Interactive Messages (кнопки) — callback endpoint
12. Протестировать полный Сценарий 1 без транскрибации и публикации (текстовые материалы → лонгрид → ревью → тест → финал)

### Фаза 4: Транскрибация
13. `transcription.py` — интеграция с Transkriptor API
14. `content_processor.py` — извлечение текста из файлов
15. Протестировать: эксперт загружает видео → транскрибация → лонгрид

### Фаза 5: Кампус
16. `campus.py` — интеграция с Campus API (по документации)
17. Протестировать: публикация курса, проверка дублей

### Фаза 6: Сценарий 2
18. Добавить обработку инициативы эксперта в `commands.py`
19. Добавить переходы Сценария 2 в `engine.py`
20. Проверка дублей через `campus.py`

### Фаза 7: Надёжность
21. `reminders.py` — таймауты и напоминания
22. Retry-логика для всех внешних API
23. Логирование
24. Docker + docker-compose

---

## Тестирование

### Как тестировать локально

1. Запустить Mattermost через docker-compose
2. Создать бот-аккаунт в Mattermost: System Console → Integrations → Bot Accounts
3. Прописать токен в `.env`
4. Создать 2 тестовых пользователя (методолог и эксперт)
5. Запустить бот: `uvicorn src.main:app --reload`
6. Написать боту от имени методолога

### Unit-тесты (pytest)

- `test_commands.py` — парсинг intent (мокнуть Claude API)
- `test_orchestrator.py` — переходы стейт-машины (мокнуть все сервисы)
- `test_llm.py` — формирование промптов (без реальных запросов)
- `test_transcription.py` — логика polling (мокнуть Transkriptor API)

---

## Критически важные замечания

1. **Всё общение через DM.** Бот общается с каждым пользователем в личных сообщениях Mattermost, не в публичных каналах.

2. **Один бот — множество задач.** Бот может вести несколько задач параллельно с разными экспертами. Каждое входящее сообщение нужно привязать к правильной задаче по `user_id` и `channel_id`.

3. **Контекст задачи.** Если у пользователя несколько активных задач — бот должен спросить, к какой задаче относится сообщение.

4. **Файлы в Mattermost.** Когда пользователь прикрепляет файл, Mattermost отправляет `file_ids` в объекте поста. Нужно скачать каждый файл через `GET /api/v4/files/{file_id}`.

5. **Interactive Messages callback URL** должен быть доступен из Mattermost. При локальной разработке: бот и Mattermost в одной docker-сети, callback URL = `http://bot:8000/api/v1/mattermost/interactive`.

6. **Transkriptor polling.** Транскрибация может занимать минуты. Не блокировать основной поток. Использовать `asyncio.create_task` для polling, обновлять задачу через callback.
