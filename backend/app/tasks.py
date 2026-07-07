"""
The two-stage Celery pipeline: OCR a PDF, then chunk/embed/index the result.

Job status (queued/ocr_processing/embedding/done/failed) is tracked in a
plain Redis hash per job_id, separate from Celery's own result backend. This
is what lets /status/{job_id} report one unified status across both tasks.
"""
import json
import traceback

import redis

from app import config
from app.celery_app import celery_app
from app.ocr import OCRError, pdf_to_text
from app.rag import add_chunks_to_index, chunk_text

_redis_client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)


def _status_key(job_id: str) -> str:
    return f"{config.JOB_STATUS_KEY_PREFIX}{job_id}"


def set_job_status(job_id: str, **fields) -> None:
    """Merge `fields` into the job's status hash in Redis."""
    # Redis hashes only store strings, so anything non-string gets JSON-encoded.
    clean = {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in fields.items()}
    _redis_client.hset(_status_key(job_id), mapping=clean)


def get_job_status(job_id: str) -> dict | None:
    data = _redis_client.hgetall(_status_key(job_id))
    if not data:
        return None
    # Try to decode any JSON-encoded numeric fields back to numbers.
    result = {}
    for key, value in data.items():
        try:
            result[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            result[key] = value
    return result


@celery_app.task(bind=True, name="process_pdf_ocr")
def process_pdf_ocr(self, job_id: str, file_path: str):
    """Stage 1: convert PDF pages to images and OCR them."""
    try:
        set_job_status(job_id, status="ocr_processing", current=0, total=0)

        def on_page_done(current, total):
            set_job_status(job_id, current=current, total=total)
            self.update_state(state="PROGRESS", meta={"current": current, "total": total})

        text = pdf_to_text(file_path, on_page_done=on_page_done)

        output_path = config.OUTPUT_DIR / f"{job_id}.txt"
        output_path.write_text(text, encoding="utf-8")

    except OCRError as exc:
        set_job_status(job_id, status="failed", error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - never let a bad PDF crash the worker
        set_job_status(job_id, status="failed", error=f"Unexpected OCR error: {exc}")
        traceback.print_exc()
        return

    # Kick off stage 2 now that OCR text is on disk.
    embed_and_index.delay(job_id)


@celery_app.task(bind=True, name="embed_and_index")
def embed_and_index(self, job_id: str):
    """Stage 2: chunk the OCR text, embed it, and upsert into the Qdrant vector store."""
    try:
        set_job_status(job_id, status="embedding")

        output_path = config.OUTPUT_DIR / f"{job_id}.txt"
        if not output_path.exists():
            raise RuntimeError("OCR output file is missing")

        text = output_path.read_text(encoding="utf-8")
        chunks = chunk_text(text)

        job_info = get_job_status(job_id) or {}
        filename = job_info.get("filename", f"{job_id}.pdf")

        add_chunks_to_index(job_id, filename, chunks)

        set_job_status(job_id, status="done")

    except Exception as exc:  # noqa: BLE001 - report failure instead of crashing
        set_job_status(job_id, status="failed", error=f"Failed to embed/index text: {exc}")
        traceback.print_exc()
