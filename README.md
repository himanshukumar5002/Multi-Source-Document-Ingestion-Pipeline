# Multi-PDF OCR + RAG Pipeline

Upload multiple PDFs, OCR them asynchronously with Tesseract via a Redis-backed
Celery queue, chunk + embed the extracted text into a Qdrant vector database, and
ask questions answered with RAG (retrieval-augmented generation via OpenAI).

```
project-root/
├── backend/     FastAPI + Celery + OCR + RAG
├── frontend/    React + Vite UI
└── docker-compose.yml   optional: redis + qdrant + backend + celery worker
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed and on `PATH`
- [Poppler](https://github.com/oschwartz10612/poppler-windows) installed and on `PATH` (needed by `pdf2image`)
- Redis (local install, WSL, or Docker)
- Qdrant (easiest via Docker)
- An OpenAI API key

## Run locally (5 services, start in this order)

### 1. Redis

```bash
redis-server
# or: docker run -p 6379:6379 redis:7
```

### 2. Qdrant (vector database)

```bash
docker run -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.1
```

### 3. Celery worker

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env   # then edit .env and set OPENAI_API_KEY
celery -A app.celery_app worker --loglevel=info --pool=solo   # --pool=solo required on Windows
```

### 4. FastAPI backend

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

### 5. Frontend (Vite dev server)

```bash
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**.

## Optional: Docker Compose

`docker-compose.yml` brings up Redis, Qdrant, the FastAPI backend, and a Celery
worker (Tesseract + Poppler are installed in `backend/Dockerfile`). The
frontend still runs locally via `npm run dev`.

```bash
docker compose up --build
```

Make sure `backend/.env` exists with `OPENAI_API_KEY` set before running this.

## How it works

1. **Upload** — `POST /upload` saves each PDF under `backend/uploads/{job_id}.pdf`
   and enqueues a `process_pdf_ocr` Celery task.
2. **OCR stage** — converts each page to an image (`pdf2image`) and runs
   `pytesseract` on it, reporting progress via `update_state`. Text is saved
   to `backend/outputs/{job_id}.txt`, then it enqueues `embed_and_index`.
3. **Embedding stage** — chunks the text (sliding window, ~500 words with
   ~50 word overlap), embeds chunks with `sentence-transformers`
   (`all-MiniLM-L6-v2`), and upserts them into the Qdrant collection
   (`pdf_chunks`) as points with metadata payloads.
4. **Ask** — `POST /ask` embeds the question, retrieves the top-k similar
   chunks from Qdrant (optionally scoped to specific `job_ids` via a
   server-side payload filter), and calls OpenAI's `gpt-4.1` with the
   retrieved context to produce a cited answer.
5. The React frontend polls `GET /status/{job_id}` every ~1.5s while a job
   is in progress, and lets you view raw OCR text or ask questions once at
   least one document is `done`.

See [backend/README.md](backend/README.md) for backend-specific details.
