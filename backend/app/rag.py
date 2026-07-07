"""
Everything RAG-related: chunking, embeddings, the Qdrant vector store, and
the final LLM call.

Qdrant runs as a separate service (see docker-compose / README), so unlike a
local FAISS file it handles concurrent access from both the Celery worker and
the FastAPI process -- no file locking needed. Each chunk is stored as a
Qdrant "point": the embedding vector plus a payload holding the chunk text
and its metadata (job_id, filename, chunk index).
"""
import uuid
from typing import List, Optional

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from app import config

_embedding_model: Optional[SentenceTransformer] = None
_openai_client: Optional[OpenAI] = None
_qdrant_client: Optional[QdrantClient] = None


def get_embedding_model() -> SentenceTransformer:
    """Lazily load the embedding model once per process (worker or API)."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to backend/.env")
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def get_qdrant_client() -> QdrantClient:
    """
    Connect to the Qdrant server and make sure our collection exists.
    Cached per process so we don't reconnect on every call.
    """
    global _qdrant_client
    if _qdrant_client is None:
        try:
            client = QdrantClient(url=config.QDRANT_URL)
            _ensure_collection(client)
        except Exception as exc:  # connection refused, etc.
            raise RuntimeError(
                f"Could not connect to Qdrant at {config.QDRANT_URL}. "
                f"Is the Qdrant server running? ({exc})"
            ) from exc
        _qdrant_client = client
    return _qdrant_client


def _ensure_collection(client: QdrantClient) -> None:
    """Create the collection on first use, sized to the embedding model."""
    existing = {c.name for c in client.get_collections().collections}
    if config.QDRANT_COLLECTION in existing:
        return

    dim = get_embedding_model().get_sentence_embedding_dimension()
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        # Cosine distance -- Qdrant normalizes vectors internally, so we don't
        # need to L2-normalize the embeddings ourselves like we did with FAISS.
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def chunk_text(
    text: str,
    chunk_size: int = config.CHUNK_SIZE_WORDS,
    overlap: int = config.CHUNK_OVERLAP_WORDS,
) -> List[str]:
    """
    Simple sliding-window chunker over whitespace-split words. Using word
    count as a stand-in for token count keeps this dependency-free and easy
    to follow -- good enough for this use case, not exact token accounting.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
    return chunks


def add_chunks_to_index(job_id: str, filename: str, chunks: List[str]) -> int:
    """
    Embed `chunks` and upsert them into Qdrant as points with metadata payloads.
    Returns the number of chunks added.
    """
    if not chunks:
        return 0

    embeddings = get_embedding_model().encode(chunks, convert_to_numpy=True)
    client = get_qdrant_client()

    points = []
    for chunk_index, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),  # Qdrant needs a unique point id
                vector=vector.tolist(),
                payload={
                    "job_id": job_id,
                    "filename": filename,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk,
                },
            )
        )

    client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
    return len(chunks)


def search(query: str, top_k: int = config.TOP_K_RESULTS, job_ids: Optional[List[str]] = None):
    """
    Return the top_k most similar chunks to `query`. Unlike FAISS, Qdrant can
    pre-filter by payload, so restricting to specific job_ids is a server-side
    filter rather than over-fetch-and-filter in Python.
    """
    client = get_qdrant_client()

    query_vec = get_embedding_model().encode([query], convert_to_numpy=True)[0]

    query_filter = None
    if job_ids:
        query_filter = Filter(
            must=[FieldCondition(key="job_id", match=MatchAny(any=job_ids))]
        )

    response = client.query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=query_vec.tolist(),
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )

    results = []
    for point in response.points:
        payload = point.payload or {}
        results.append(
            {
                "job_id": payload.get("job_id"),
                "filename": payload.get("filename"),
                "chunk_text": payload.get("chunk_text"),
                "score": float(point.score),
            }
        )
    return results


def build_prompt(question: str, chunks: list) -> list:
    context = "\n\n---\n\n".join(
        f"[{c['filename']}] {c['chunk_text']}" for c in chunks
    )
    system_message = (
        "You are a helpful assistant answering questions about documents that "
        "were extracted via OCR. Use only the provided context to answer. "
        "If the answer isn't in the context, say you don't know."
    )
    user_message = f"Context:\n{context}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def answer_question(question: str, job_ids: Optional[List[str]] = None) -> dict:
    """Run the full RAG flow: retrieve chunks, call the LLM, return answer + sources."""
    chunks = search(question, top_k=config.TOP_K_RESULTS, job_ids=job_ids)

    if not chunks:
        return {
            "answer": "No indexed documents found to answer this question yet.",
            "sources": [],
        }

    messages = build_prompt(question, chunks)

    client = get_openai_client()
    response = client.chat.completions.create(
        model=config.LLM_MODEL_NAME,
        messages=messages,
    )
    answer = response.choices[0].message.content

    return {"answer": answer, "sources": chunks}
