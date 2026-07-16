"""Embedding interface and the production sentence-transformers backend.

The :class:`Embedder` protocol lets tests inject a deterministic fake so no
model is downloaded and no network is used. The production implementation
loads a :class:`SentenceTransformer` once and reuses it for every call,
returning L2-normalized vectors suitable for cosine similarity.
"""

from typing import Protocol

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class Embedder(Protocol):
    """Turns texts into embedding vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one normalized embedding per input text."""
        ...


class SentenceTransformerEmbedder:
    """Production embedder backed by sentence-transformers.

    The model is loaded lazily on first use and then reused, never reloaded
    per record or request.
    """

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            # Imported lazily so importing this module never pulls in torch.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(  # type: ignore[attr-defined]
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]
