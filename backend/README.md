# Backend — Multi-PDF OCR + RAG API

FastAPI + Celery + Redis + Tesseract + Qdrant + OpenAI.

## Prerequisites

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed and on your `PATH`
  (Windows: install from the [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki), then
  add the install dir, e.g. `C:\Program Files\Tesseract-OCR`, to `PATH`)
- [Poppler](https://github.com/oschwartz10612/poppler-windows) installed and on your `PATH`
  (required by `pdf2image` to rasterize PDF pages)
- Redis server available (locally, via Docker, or WSL)
- Qdrant vector database (easiest via Docker: `docker run -p 6333:6333 qdrant/qdrant`)

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt

copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux
# then edit .env and set OPENAI_API_KEY
```

## Running (start in this order, each in its own terminal)

**1. Redis**

```bash
redis-server
# or: docker run -p 6379:6379 redis:7
```

**2. Qdrant**

```bash
docker run -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.1
```

**3. Celery worker**

```bash
cd backend
celery -A app.celery_app worker --loglevel=info --pool=solo
```

> `--pool=solo` is needed on Windows (Celery's default prefork pool doesn't
> work there). On macOS/Linux you can drop it.

**4. FastAPI (Uvicorn)**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**5. Frontend** — see [../frontend/README instructions in the top-level README](../README.md).

## API

| Method | Path                 | Description                                   |
|--------|----------------------|------------------------------------------------|
| POST   | `/upload`             | Upload one or more PDFs, returns job IDs       |
| GET    | `/status/{job_id}`    | Current status + progress of a job             |
| GET    | `/result/{job_id}`    | Raw OCR text once status is `done`             |
| POST   | `/ask`                | RAG question answering across indexed docs     |

## Notes / limitations

- Vectors are stored in Qdrant, which runs as its own service. Both the
  Celery worker and the API talk to it over HTTP, so concurrent access is
  handled by Qdrant (no file locking needed). Each chunk is one Qdrant point:
  the embedding vector plus a payload with `job_id`, `filename`,
  `chunk_index`, and `chunk_text`. Filtering `/ask` by `job_ids` is a
  server-side payload filter.
- Job status lives in a Redis hash per job (`job_status:{job_id}`), separate
  from Celery's own result backend, so a single `/status` call can reflect
  both the OCR stage and the embedding stage.
