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
