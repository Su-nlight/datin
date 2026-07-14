"""
app/providers/pinecone_provider.py

Same PineconeDB class as Backend/API/pineconedb.py's PineconeDB, minus
load_dotenv(). The MitreVectorUploader / CsvVectorUploader ingestion
helpers move to app/services/ingestion_service.py (they're application
logic, not a "provider" — a provider should just be a thin client wrapper).
"""
import json
import os
import uuid
from typing import List, Optional

import torch
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

from app.config import Settings


class PineconeProvider:
    def __init__(
        self,
        settings: Settings,
        index_name: Optional[str] = None,
        user_namespace: str = "",
        embedding_fields: Optional[List[str]] = None,
        batch_size: int = 127,
    ):
        self.settings = settings
        self.pinecone = Pinecone(api_key=settings.PINECONE_API_KEY)
        self.user_namespace = user_namespace
        self.index = self._create_index(index_name or settings.INDEX_NAME)

        self.model = SentenceTransformer(
            settings.MODEL, device="cuda" if torch.cuda.is_available() else "cpu"
        )
        self.fields = embedding_fields
        self.batch_size = batch_size

    def _create_index(self, index_name: str):
        existing = self.pinecone.list_indexes().names()
        if index_name not in existing:
            self.pinecone.create_index(
                name=index_name,
                dimension=1024,
                metric=self.settings.SIMILARITY,
                spec=ServerlessSpec(cloud=self.settings.CLOUD, region=self.settings.REGION),
            )
        return self.pinecone.Index(index_name)

    def create_embedding(self, item: dict) -> list:
        text_to_embed = ""
        if self.fields:
            text_to_embed = " ".join(str(item.get(f, "")) for f in self.fields).strip()
        if not text_to_embed:
            try:
                text_to_embed = json.dumps(item, ensure_ascii=False)
            except Exception:
                text_to_embed = str(item)
        return self.model.encode(text_to_embed, normalize_embeddings=True).tolist()

    def upsert(self, batch_vectors: list) -> None:
        self.index.upsert(vectors=batch_vectors, namespace=self.user_namespace)

    def query(self, query_text: str, top_k: int = 5) -> dict:
        embedding = self.model.encode(query_text, normalize_embeddings=True).tolist()
        return self.index.query(
            vector=embedding, top_k=top_k, include_metadata=True, namespace=self.user_namespace
        )

    def query_multiple_namespaces(
        self, query_text: str, namespaces: List[str], min_score: float = 0.7
    ) -> dict:
        if not (0.1 <= min_score <= 0.9):
            raise ValueError("min_score must be between 0.1 and 0.9")

        embedding = self.model.encode(query_text, normalize_embeddings=True).tolist()
        results = {}
        for ns in namespaces:
            result = self.index.query(
                vector=embedding, top_k=4, include_metadata=True, namespace=ns
            ).to_dict()
            results[ns] = [
                m["metadata"] for m in result.get("matches", []) if m.get("score", 0) > min_score
            ]
        return results