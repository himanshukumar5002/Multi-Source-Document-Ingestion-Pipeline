"""
Central place for all settings. Everything is loaded from environment
variables (via a .env file in backend/) so secrets never get hardcoded.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Filesystem locations ---------------------------------------------
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

# Make sure these exist on startup so tasks/routes never fail on a missing dir.
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Qdrant vector store --------------------------------------------------
# Qdrant runs as a separate service (Docker), so both the worker and the API
# talk to it over HTTP. Vectors persist inside the Qdrant container's volume.
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pdf_chunks")

# --- Redis / Celery ------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# Job status hashes are stored in Redis directly (separate from Celery's own
# result backend) so /status can report a single unified status across the
# two chained tasks (OCR stage + embedding stage).
JOB_STATUS_KEY_PREFIX = "job_status:"

# --- OCR binaries (Windows PATH is finicky, so allow explicit paths) --------
# If set, these override PATH lookup. Leave blank to rely on PATH.
POPPLER_PATH = os.getenv("POPPLER_PATH", "")  # folder containing pdftoppm.exe
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")  # full path to tesseract.exe

# --- OpenAI / LLM ---------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4.1")

# --- Embeddings / RAG ------------------------------------------------------
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
CHUNK_SIZE_WORDS = int(os.getenv("CHUNK_SIZE_WORDS", "500"))
CHUNK_OVERLAP_WORDS = int(os.getenv("CHUNK_OVERLAP_WORDS", "50"))
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "5"))

# --- CORS ------------------------------------------------------------------
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
]
