"""
OCR helpers: turn a PDF into plain text.

Kept separate from tasks.py so the OCR logic can be unit-tested or reused
without pulling in Celery.
"""
from pathlib import Path
from typing import Callable, Optional

import pytesseract
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError
from pytesseract import TesseractNotFoundError

from app import config

# If an explicit tesseract path is configured, use it instead of relying on PATH.
if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


class OCRError(Exception):
    """Raised when a PDF can't be OCR'd (corrupt file, missing Tesseract, etc)."""


def pdf_to_text(
    file_path: str,
    on_page_done: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    Convert every page of the PDF at `file_path` to an image, OCR each image,
    and return the concatenated text.

    `on_page_done(current_page, total_pages)` is called after each page so
    the caller can report progress (e.g. via Celery's update_state).
    """
    try:
        # poppler_path=None makes pdf2image fall back to PATH, so passing an
        # empty config value is harmless.
        pages = convert_from_path(file_path, poppler_path=config.POPPLER_PATH or None)
    except (PDFPageCountError, PDFSyntaxError) as exc:
        raise OCRError(f"Could not read PDF (corrupt or unsupported file): {exc}") from exc
    except Exception as exc:  # poppler missing, permission errors, etc.
        raise OCRError(f"Failed to convert PDF to images: {exc}") from exc

    if not pages:
        raise OCRError("PDF has no pages to OCR")

    total_pages = len(pages)
    page_texts = []

    for i, page_image in enumerate(pages, start=1):
        try:
            page_texts.append(pytesseract.image_to_string(page_image))
        except TesseractNotFoundError as exc:
            raise OCRError(
                "Tesseract binary not found. Make sure it is installed and on PATH."
            ) from exc
        except Exception as exc:
            raise OCRError(f"OCR failed on page {i}: {exc}") from exc

        if on_page_done:
            on_page_done(i, total_pages)

    return "\n\n".join(page_texts).strip()
