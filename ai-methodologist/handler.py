import os
import logging
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

        if status == "INTERVIEW":
            self._handle_interview_answers(task, message)
        elif status == "WAITING_MATERIALS":
            self._handle_materials(task, message, file_ids)
        elif status == "STRUCTURE_PROPOSAL" and not file_ids:
            self._handle_structure_feedback(task, message)
        elif status == "REVIEW_EXPERT" and not file_ids:
            self._handle_expert_feedback_text(task, message)
        elif status == "REVIEW_TEST" and not file_ids:
            self._handle_test_feedback_text(task, message)
        elif status == "REVIEW_METHODOLOGIST" and not file_ids:
            self._handle_methodologist_feedback_text(task, message)
        else:
            self.bot.send_message(
                channel_id,
                "Получил твоё сообщение. Если нужно что-то изменить, воспользуйся кнопками выше.",
            )

    def handle_button(self, task_id: str, action: str, user_id: str):
        task = self.state.get_task(task_id)
        if not task:
            logger.warning(f"Button click for unknown task {task_id}")
            return

        status = task["status"]
        dispatch = {
            ("STRUCTURE_PROPOSAL", "confirm_structure"): self._on_confirm_structure,
            ("STRUCTURE_PROPOSAL", "edit_structure"): self._on_edit_structure,
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
                self.bot.send_message(
                    channel,
                    "Произошла ошибка при обработке. Попробуй ещё раз или обратись к методологу.",
                )
        else:
            logger.warning(f"No handler for ({status}, {action})")

    # ---- New conversation ----

    def _handle_new_conversation(self, user_id: str, channel_id: str, message: str, file_ids: list):
        greeting_words = {"привет", "hello", "hi", "добрый", "здравствуй", "хай", "хэй", "ку"}
        msg_words = set(message.lower().split())
        is_greeting = bool(msg_words & greeting_words) and len(msg_words) <= 4

        if is_greeting:
            self.bot.send_message(
                channel_id,
                "Привет! Я методолог и помогу тебе создать обучающий курс и загрузить его на платформу Campus.\n\n"
                "Расскажи подробнее, какая у тебя идея курса и что ты планируешь сделать?",
            )
            return

        intent_data = self.llm.parse_intent(message)
        intent = intent_data.get("intent")

        if intent != "create_course":
            self.bot.send_message(
                channel_id,
                "Привет! Я методолог и помогу тебе создать обучающий курс и загрузить его на платформу Campus.\n\n"
                "Расскажи подробнее, какая у тебя идея курса и что ты планируешь сделать?",
            )
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
        self.state.update_task(task_id, status="INTERVIEW")
        self.bot.send_message(
            channel_id,
            "Класс, давай уточним детали, чтобы собрать сильный курс 👇\n\n"
            "🎯 *Цели курса*\n"
            "• Какая основная цель курса?\n"
            "• Как планируешь оценивать результат?\n"
            "  (например: тест, кейсы, практика, внедрение в работу, метрики)\n\n"
            "👥 *Целевая аудитория*\n"
            "• Кто будет проходить этот курс?\n"
            "• Какой у них уровень знаний по теме?\n\n"
            "🧩 *Содержание курса*\n"
            "• Какие блоки или темы обязательно должны быть в курсе?\n"
            "• Есть ли уже структура или нужно помочь её собрать?",
        )

    # ---- State handlers ----

    def _handle_interview_answers(self, task: dict, message: str):
        if not message.strip():
            return
        self.state.update_task(task["id"], interview_answers=message, status="WAITING_MATERIALS")
        self.bot.send_message(
            task["expert_channel_id"],
            "Отлично, теперь давай соберём материалы для курса.\n\n"
            "Загрузи всё, что у тебя есть — это могут быть:\n"
            "– презентации\n"
            "– PDF-документы\n"
            "– текстовые файлы\n"
            "– записи встреч или вебинаров\n"
            "– любые другие материалы\n\n"
            "Если материалов несколько — загружай всё, я обработаю.",
        )

    def _handle_materials(self, task: dict, message: str, file_ids: list):
        if not file_ids and not message.strip():
            self.bot.send_message(
                task["expert_channel_id"],
                "Не вижу файлов. Прикрепи файл к сообщению или напиши текст напрямую.",
            )
            return

        self.bot.send_message(
            task["expert_channel_id"],
            "Получил материалы! ⏳ Обрабатываю — это займёт несколько минут...",
        )
        self.state.update_task(task["id"], status="PROCESSING")

        texts = []
        for fid in file_ids:
            try:
                # Fetch real filename from Mattermost file metadata
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
                        self.bot.send_message(
                            task["expert_channel_id"],
                            self.transcription.get_stub_message(),
                        )
                    continue
                text = self.files.extract_text(save_path)
                if text:
                    texts.append(text)
            except Exception as e:
                logger.exception(f"File processing error for {fid}: {e}")

        if message.strip():
            texts.append(message.strip())

        if not texts:
            self.state.update_task(task["id"], status="WAITING_MATERIALS")
            self.bot.send_message(
                task["expert_channel_id"],
                "Не удалось извлечь текст из файлов. "
                "Попробуй загрузить .docx или .txt файл.",
            )
            return

        source_text = "\n\n---\n\n".join(texts)
        self.state.update_task(task["id"], source_text=source_text)

        try:
            with self.bot.typing_while(task["expert_channel_id"]):
                structure = self.llm.generate_structure(
                    task["topic"],
                    source_text,
                    task.get("interview_answers") or "",
                )
        except LLMError:
            self.state.update_task(task["id"], status="WAITING_MATERIALS")
            self.bot.send_message(
                task["expert_channel_id"],
                "❌ Ошибка при анализе материалов. Попробуй загрузить файлы ещё раз.",
            )
            return

        self.state.update_task(task["id"], status="STRUCTURE_PROPOSAL", proposed_structure=structure)
        self._send_structure_proposal(task["id"], task["expert_channel_id"], structure)

    def _send_structure_proposal(self, task_id: str, channel_id: str, structure: str):
        self.bot.send_message(
            channel_id,
            f"Я посмотрела материалы и предлагаю такую структуру курса 👇\n\n{structure}\n\n"
            "Посмотри, пожалуйста, подходит ли такая структура?\n"
            "Хочешь что-то добавить, убрать или поменять?",
        )
        self.bot.send_buttons(
            channel_id,
            "Твоё решение:",
            [
                {"name": "✅ Подходит", "context": {"task_id": task_id, "action": "confirm_structure"}},
                {"name": "✏️ Хочу изменить", "context": {"task_id": task_id, "action": "edit_structure"}},
            ],
        )

    def _on_confirm_structure(self, task: dict):
        self.bot.send_message(
            task["expert_channel_id"],
            "⏳ Отлично! Генерирую полный курс на основе структуры — это займёт несколько минут...",
        )
        task = self.state.get_task(task["id"])
        try:
            with self.bot.typing_while(task["expert_channel_id"]):
                longread = self.llm.generate_longread(
                    task["topic"],
                    task["source_text"],
                    structure=task.get("proposed_structure") or "",
                    interview_answers=task.get("interview_answers") or "",
                )
        except LLMError:
            self.bot.send_message(
                task["expert_channel_id"],
                "❌ Ошибка при генерации курса. Попробуй ещё раз — нажми «Подходит».",
            )
            return
        self.state.update_task(
            task["id"],
            status="REVIEW_EXPERT",
            longread=longread,
            longread_version=1,
            longread_edit_count=0,
        )
        self.bot.send_message(task["expert_channel_id"], "Готово! Вот структура и содержание курса 👇")
        self._send_longread_for_review(task["id"], task["expert_channel_id"], longread, version=1)

    def _on_edit_structure(self, task: dict):
        self.bot.send_message(
            task["expert_channel_id"],
            "Напиши, что хочешь изменить в структуре — я обновлю.",
        )

    def _handle_structure_feedback(self, task: dict, message: str):
        if not message.strip():
            return
        task = self.state.get_task(task["id"])
        if task["status"] != "STRUCTURE_PROPOSAL":
            return
        self.bot.send_message(task["expert_channel_id"], "⏳ Обновляю структуру...")
        try:
            with self.bot.typing_while(task["expert_channel_id"]):
                current = task.get("proposed_structure") or ""
                updated_structure = self.llm.apply_edits(current, message)
        except LLMError:
            self.bot.send_message(task["expert_channel_id"],
                "❌ Ошибка при обновлении структуры. Попробуй ещё раз.")
            return
        self.state.update_task(task["id"], proposed_structure=updated_structure)
        self._send_structure_proposal(task["id"], task["expert_channel_id"], updated_structure)

    def _send_longread_for_review(self, task_id: str, channel_id: str, longread: str, version: int):
        tmp = f"{UPLOAD_DIR}/{task_id}_longread_v{version}.md"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(longread)
        self.bot.send_file(channel_id, tmp,
            f"📝 Лонгрид готов (версия {version}). Посмотри — всё ли верно по содержанию?")
        self.bot.send_buttons(
            channel_id,
            "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task_id, "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task_id, "action": "request_changes"}},
            ],
        )

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
            self.bot.send_message(
                task["expert_channel_id"],
                f"Мы уже внесли {MAX_EDITS} правок. "
                "Предлагаю обсудить оставшиеся правки лично с методологом.",
            )
            return
        self.bot.send_message(task["expert_channel_id"],
            "Напиши, что нужно изменить — я внесу правки.")

    def _handle_expert_feedback_text(self, task: dict, feedback: str):
        if not feedback.strip():
            return
        task = self.state.get_task(task["id"])
        if task["status"] != "REVIEW_EXPERT":
            return
        try:
            with self.bot.typing_while(task["expert_channel_id"]):
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
        self.bot.send_message(task["expert_channel_id"], "⏳ Генерирую проверочное задание...")
        try:
            with self.bot.typing_while(task["expert_channel_id"]):
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
        self.bot.send_buttons(
            channel_id,
            "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task_id, "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task_id, "action": "request_changes"}},
            ],
        )

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
                f"Мы уже внесли {MAX_EDITS} правок в тест. Предлагаю обсудить с методологом.")
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
        self.bot.send_message(
            meth_channel,
            f"📚 Новый материал готов к проверке!\n\n"
            f"**Тема:** {task['topic']}\n\n"
            f"Прилагаю лонгрид{test_info}. Посмотри и одобри или оставь комментарии.",
        )
        self.bot.send_file(meth_channel, longread_path, "📄 Лонгрид:")
        if test_path:
            self.bot.send_file(meth_channel, test_path, "📋 Тест:")
        self.bot.send_buttons(
            meth_channel,
            "Твоё решение:",
            [
                {"name": "✅ Одобрить", "context": {"task_id": task["id"], "action": "approve"}},
                {"name": "✏️ Нужны правки", "context": {"task_id": task["id"], "action": "request_changes"}},
            ],
        )

    def _on_methodologist_approve(self, task: dict):
        self.state.update_task(task["id"], status="DONE")
        self.bot.send_message(task["methodologist_channel_id"],
            "✅ Отлично! Материал отмечен как согласованный.")
        self.bot.send_message(
            task["expert_channel_id"],
            f"🎉 Материал по теме «{task['topic']}» согласован методологом!\n\n"
            "Методолог свяжется с тобой по поводу публикации на платформе.",
        )

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
            with self.bot.typing_while(task["methodologist_channel_id"]):
                updated_longread = self.llm.apply_edits(task["longread"], feedback)
        except LLMError:
            self.bot.send_message(task["methodologist_channel_id"],
                "❌ Ошибка при применении правок. Попробуй ещё раз.")
            return
        version = (task.get("longread_version") or 1) + 1
        self.state.update_task(task["id"],
            longread=updated_longread, longread_version=version)
        self._send_to_methodologist(task)
