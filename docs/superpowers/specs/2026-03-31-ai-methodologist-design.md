# Дизайн: ИИ-Методолог — MVP

**Дата:** 2026-03-31
**Версия:** 1.0
**Автор:** Таня + Claude

---

## 1. Цель и контекст

Mattermost-бот, который автоматизирует создание обучающих курсов. Эксперт пишет боту в личку, загружает материалы (документы, видео), бот генерирует лонгрид и тест через Claude API, проводит циклы согласования с экспертом и методологом.

**MVP scope:**
- Только Сценарий 2: эксперт инициирует создание курса
- Публикация на Кампус — вне scope (добавляется в следующей версии)
- Транскрибация видео — заглушка на старте (работает с текстовыми файлами, DOCX, PDF)
- Запуск на локальном компьютере разработчика

---

## 2. Архитектура

### Файловая структура

```
ai-methodologist/
├── .env                  ← API ключи и токены (не коммитить в git!)
├── .env.example          ← шаблон с пустыми значениями
├── requirements.txt      ← зависимости Python
├── main.py               ← FastAPI + uvicorn: HTTP-сервер для кнопок + запуск бота
│
├── bot.py                ← подключение к Mattermost (WebSocket + REST)
├── handler.py            ← обработка входящих сообщений и button callbacks
├── state.py              ← стейт-машина, хранение в SQLite (bot.db)
│
├── services/
│   ├── llm.py            ← Claude API: intent, лонгрид, тест, правки
│   ├── transcription.py  ← Transkriptor API (заглушка на старте)
│   └── files.py          ← извлечение текста из DOCX/PDF/PPTX/TXT
│
├── prompts/
│   ├── longread.py       ← промпты для генерации лонгрида
│   └── test.py           ← промпты для генерации теста
│
└── data/
    └── uploads/          ← временные файлы (в .gitignore)
```

### Компоненты и их роли

| Компонент | Роль |
|---|---|
| `bot.py` | Подключение к Mattermost через WebSocket. Приём сообщений и файлов. Отправка текста, файлов, кнопок. Дедупликация сообщений. Авто-переподключение. |
| `handler.py` | Главная логика: получает событие от бота → определяет intent через Claude → передаёт в стейт-машину → отправляет ответ |
| `state.py` | Хранит текущее состояние каждой задачи в SQLite (`bot.db`). Методы: get_task, create_task, update_task, set_status. Использует стандартную библиотеку `sqlite3` с блокировкой через WAL-mode для безопасного доступа из нескольких потоков. |
| `services/llm.py` | Обёртка Claude API: parse_intent(), generate_longread(), apply_edits(), generate_test(), apply_test_edits() |
| `services/transcription.py` | Transkriptor: transcribe_file(), transcribe_url(), get_status(). На старте — заглушка, возвращает «транскрибация недоступна, загрузите текстовый файл» |
| `services/files.py` | Извлечение текста: DOCX (python-docx), PDF (pdfplumber), PPTX (python-pptx), TXT (прямое чтение) |
| `prompts/longread.py` | Системный промпт + пользовательский промпт для лонгрида. Стиль: дружелюбный, без канцеляризмов, Markdown, 3000-10000 символов |
| `prompts/test.py` | Промпты для quiz (JSON), кейса (JSON), открытых вопросов (JSON) |

---

## 3. Поток работы (Сценарий 2)

```
Эксперт: «Хочу сделать курс по теме X»
    ↓
[INIT] Бот парсит intent → тема извлечена
    ↓
[CHECKING_DUPLICATES] В MVP: заглушка — бот сразу отвечает «Дублей не найдено, продолжаем?»
  → [Кнопки: ✅ Продолжить | ❌ Отменить]
  (Реальная проверка через Campus API — в следующей версии)
    ↓
[WAITING_MATERIALS] Бот: «Загрузи материалы: файл или ссылку на видео»
  → Эксперт загружает файл(ы) или отправляет ссылку
    ↓
[PROCESSING] Бот: «Получил! Обрабатываю...»
  → Извлечение текста / транскрибация
  → Генерация лонгрида через Claude
    ↓
[REVIEW_EXPERT] Бот отправляет лонгрид + кнопки:
  → [✅ Одобрить | ✏️ Нужны правки]
  → Если правки: бот спрашивает «что изменить?» → применяет → снова кнопки
  → Цикл до 5 итераций (потом: «предлагаю обсудить лично»)
    ↓
[ASK_TEST] Бот: «Нужна проверка знаний?»
  → [📝 Тест с вариантами | 📋 Кейс | ❓ Открытые вопросы | ⏭️ Не нужна]
    ↓ (если выбран тип)
[GENERATING_TEST] Генерация теста через Claude
    ↓
[REVIEW_TEST] Бот отправляет тест + кнопки: [✅ Одобрить | ✏️ Нужны правки]
  → Тот же цикл правок
    ↓
[REVIEW_METHODOLOGIST] Бот пишет методологу:
  «Новый материал от @эксперт: тема X. Лонгрид + тест готовы.»
  + прикрепляет файлы: longread.md (лонгрид) и test.json (тест, если был создан)
  + кнопки [✅ Одобрить | ✏️ Нужны правки]
    ↓
[DONE] Бот эксперту: «Материал согласован! 🎉»
```

**Состояния стейт-машины:**
`INIT → CHECKING_DUPLICATES → WAITING_MATERIALS → PROCESSING → REVIEW_EXPERT → ASK_TEST → GENERATING_TEST → REVIEW_TEST → REVIEW_METHODOLOGIST → DONE`

**Дополнительные состояния:** `CANCELLED` (эксперт нажал «Отменить»), `ERROR` (критическая ошибка)
`PAUSED` — зарезервировано для следующей версии (напоминания по таймауту), в MVP не используется.

---

## 4. Модель данных (SQLite — bot.db)

Хранится в SQLite (`bot.db`) через простую таблицу `tasks`. SQLite решает проблему одновременного доступа из WebSocket-потока и FastAPI-потока.

```
Таблица: tasks
- id                    TEXT (UUID, первичный ключ)
- status                TEXT (текущий статус)
- topic                 TEXT (тема курса)
- expert_mm_id          TEXT (Mattermost user ID эксперта)
- expert_channel_id     TEXT (ID личного канала бот↔эксперт)
- methodologist_mm_id   TEXT (из .env → METHODOLOGIST_USER_ID)
- methodologist_channel_id TEXT (ID личного канала бот↔методолог; открывается при создании задачи через Mattermost API createDirectChannel с methodologist_mm_id из .env)
- source_text           TEXT (извлечённый текст из материалов)
- longread              TEXT (лонгрид в Markdown)
- longread_version      INTEGER (счётчик версий)
- longread_edit_count   INTEGER (счётчик правок лонгрида, лимит 5)
- test                  TEXT (тест в JSON)
- test_type             TEXT (quiz / case / open_questions / null)
- test_version          INTEGER
- test_edit_count       INTEGER (счётчик правок теста, лимит 5, независим от longread_edit_count)
- needs_test            INTEGER (0/1/null)
- created_at            TEXT
- updated_at            TEXT
```

**Примечание:** `methodologist_mm_id` берётся из `.env` (переменная `METHODOLOGIST_USER_ID`), не из пользовательского ввода.

---

## 5. Важные технические решения

### Mattermost WebSocket (по SKILL.md)
- WebSocket работает в отдельном потоке — нельзя использовать async HTTP из обработчика
- Все HTTP-запросы к Mattermost API делать через sync `httpx`
- Дедупликация сообщений через `_seen_ids` set
- SSL патч для `mattermostdriver`
- Supervision loop с авто-переподключением и экспоненциальным backoff

### Claude API (intent + генерация)
- Таймаут через `threading.Timer` (не `asyncio.wait_for`) — 90 секунд
- При таймауте или ошибке API: бот сообщает пользователю «Произошла ошибка, попробуйте ещё раз», задача остаётся в текущем статусе (не теряется), одна авто-повторная попытка
- Intent parsing: короткий промпт → JSON с `{"intent": ..., "entities": {...}}`
- Генерация лонгрида: большой системный промпт + материалы как user message

### Валидация файлов
- Максимальный размер: 50 МБ (Mattermost обычно ограничивает сам, но бот дополнительно проверяет)
- Допустимые типы: DOCX, PDF, PPTX, TXT, MP4, MP3, MOV, M4A
- При нарушении: бот отвечает понятным сообщением об ошибке, задача остаётся в `WAITING_MATERIALS`

### Кнопки в Mattermost
- Interactive Messages: кнопки отправляют POST на `/api/button_callback`
- FastAPI endpoint принимает callback и передаёт в handler
- В callback context хранится `task_id` и `action`

---

## 6. Что НЕ входит в MVP

- Публикация на Кампус (следующая версия)
- Реальная транскрибация видео через Transkriptor (заглушка)
- Напоминания через таймауты (следующая версия)
- Сценарий 1 (методолог инициирует)
- Docker-контейнер
- Напоминания по таймауту (PAUSED state)

---

## 7. Чеклист перед запуском

| # | Что | Как получить |
|---|---|---|
| 1 | Python 3.11 | `brew install python@3.11` |
| 2 | Anthropic API Key | console.anthropic.com |
| 3 | Transkriptor API Key | app.transkriptor.com/account (90 мин бесплатно) |
| 4 | Mattermost URL + Bot Token | ✅ уже есть |
| 5 | Mattermost username методолога | уточнить |

---

## 8. Порядок разработки (следующие шаги)

1. Установить Python 3.11 + зависимости
2. Настроить `.env` с токенами
3. Реализовать `bot.py` — подключение и ping/pong тест
4. Реализовать `state.py` — создание и обновление задач
5. Реализовать `services/files.py` — извлечение текста
6. Реализовать `services/llm.py` — intent + генерация лонгрида
7. Реализовать `handler.py` — полный сценарий 2
8. Добавить генерацию тестов
9. Добавить Transkriptor (реальный)
10. Добавить Кампус API
