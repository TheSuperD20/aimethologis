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
    assert "большой" in msg.lower() or "размер" in msg.lower() or "мб" in msg.lower()


def test_validate_file_unsupported_type():
    ok, msg = fp.validate_file("photo.jpg", 1024)
    assert ok is False


def test_extract_text_from_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Привет мир", encoding="utf-8")
    text = fp.extract_text(str(f))
    assert "Привет мир" in text
