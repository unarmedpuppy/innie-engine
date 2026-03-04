"""Embedding server — thin FastAPI wrapper around sentence-transformers/bge-base-en-v1.5.

CPU-only, ~500MB RAM. OpenAI-compatible /v1/embeddings endpoint.
"""

import os
import time

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
CACHE_DIR = os.environ.get("CACHE_DIR", "/app/cache")
PORT = int(os.environ.get("PORT", "8766"))

app = FastAPI(title="innie-embeddings")
model: SentenceTransformer | None = None


class EmbeddingRequest(BaseModel):
    model: str = "bge-base-en"
    input: str | list[str] = ""


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: dict


@app.on_event("startup")
def load_model():
    global model
    model = SentenceTransformer(MODEL_NAME, cache_folder=CACHE_DIR)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "ready": model is not None}


@app.post("/v1/embeddings")
def create_embeddings(req: EmbeddingRequest) -> EmbeddingResponse:
    texts = [req.input] if isinstance(req.input, str) else req.input
    embeddings = model.encode(texts, normalize_embeddings=True).tolist()

    return EmbeddingResponse(
        data=[
            EmbeddingData(index=i, embedding=emb)
            for i, emb in enumerate(embeddings)
        ],
        model=req.model,
        usage={"prompt_tokens": sum(len(t.split()) for t in texts), "total_tokens": sum(len(t.split()) for t in texts)},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
