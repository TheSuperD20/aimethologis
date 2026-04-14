import os
import logging
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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
bot.login()  # called before uvicorn starts — no async conflict
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

    return JSONResponse({"update": {"message": ""}})


@app.get("/health")
async def health():
    return {"status": "ok", "bot_user_id": bot.bot_user_id}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
