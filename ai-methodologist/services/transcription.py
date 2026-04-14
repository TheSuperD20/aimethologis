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

    def transcribe_file(self, file_path: str) -> Optional[str]:
        if not self.available:
            return None
        raise NotImplementedError("Transkriptor file upload not yet implemented")

    def transcribe_url(self, url: str) -> Optional[str]:
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
