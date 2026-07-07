"""FastAPI app: upload PDFs, check status, fetch OCR results, ask questions."""
import uuid
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config
from app.rag import answer_question
from app.tasks import get_job_status, process_pdf_ocr, set_job_status

app = FastAPI(title="Multi-PDF OCR + RAG Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    # Also allow any localhost port so Vite falling back to 5174/5175/etc.
    # (when 5173 is busy) doesn't break CORS during local dev.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    job_ids: Optional[List[str]] = None


@app.post("/upload")
async def upload_pdfs(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")

    results = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            results.append(
                {"filename": file.filename, "job_id": None, "status": "rejected: not a PDF"}
            )
            continue

        job_id = uuid.uuid4().hex
        file_path = config.UPLOAD_DIR / f"{job_id}.pdf"

        try:
            contents = await file.read()
            file_path.write_bytes(contents)
        except Exception as exc:
            results.append(
                {"filename": file.filename, "job_id": job_id, "status": f"failed to save: {exc}"}
            )
            continue

        set_job_status(job_id, status="queued", filename=file.filename, current=0, total=0)
        process_pdf_ocr.delay(job_id, str(file_path))

        results.append({"filename": file.filename, "job_id": job_id, "status": "queued"})

    return results


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    status = get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {"job_id": job_id, **status}


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    status = get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if status.get("status") != "done":
        raise HTTPException(
            status_code=409, detail=f"Job is not done yet (status: {status.get('status')})"
        )

    output_path = config.OUTPUT_DIR / f"{job_id}.txt"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    text = output_path.read_text(encoding="utf-8")
    return {"job_id": job_id, "filename": status.get("filename"), "text": text}


@app.post("/ask")
async def ask_question(request: AskRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = answer_question(request.question, job_ids=request.job_ids)
    except RuntimeError as exc:
        # e.g. missing OPENAI_API_KEY
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {exc}") from exc

    return result
