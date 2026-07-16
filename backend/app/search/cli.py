"""CLI to build or update the persistent semantic-search index.

Usage (from ``backend/``)::

    python -m app.search.cli \\
        --database-url sqlite:///../data/generated/ehr_media.db \\
        --chroma-path ../data/generated/chroma

Reads valid stored Bundles and their available cached summaries and reconciles
them into the Chroma index. It never re-runs ingestion, FHIR mapping, or
summarization, and makes no Anthropic API calls.

Exit codes:
  0  index built or updated
  1  unrecoverable database or Chroma failure
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.persistence.database import create_db_engine, init_db
from app.search.embeddings import SentenceTransformerEmbedder
from app.search.index_store import open_persistent_index
from app.search.indexer import Indexer

EXIT_OK = 0
EXIT_FATAL = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.search.cli",
        description="Build or update the semantic-search index from stored data.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL (defaults to the configured DATABASE_URL)",
    )
    parser.add_argument(
        "--chroma-path",
        default=None,
        help="ChromaDB persistence path (defaults to the configured CHROMA_PATH)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Chroma collection name (defaults to the configured CHROMA_COLLECTION)",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="sentence-transformers model (defaults to the configured EMBEDDING_MODEL)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    chroma_path = args.chroma_path or settings.chroma_path
    collection = args.collection or settings.chroma_collection
    embedding_model = args.embedding_model or settings.embedding_model

    try:
        engine = create_db_engine(database_url)
        init_db(engine)
    except Exception as exc:  # noqa: BLE001 - configuration/db failure is fatal
        print(f"error: could not open database '{database_url}': {exc}", file=sys.stderr)
        return EXIT_FATAL

    try:
        embedder = SentenceTransformerEmbedder(embedding_model)
        index = open_persistent_index(path=chroma_path, collection=collection, embedder=embedder)
    except Exception as exc:  # noqa: BLE001 - Chroma/model failure is fatal
        print(f"error: could not open the search index: {exc}", file=sys.stderr)
        engine.dispose()
        return EXIT_FATAL

    try:
        with Session(engine) as session:
            report = Indexer(session=session, index=index).reindex_all()
    except Exception as exc:  # noqa: BLE001 - reported without a stack trace
        print(f"error: indexing failed: {exc}", file=sys.stderr)
        return EXIT_FATAL
    finally:
        engine.dispose()

    print(f"model:        {embedding_model}")
    print(f"collection:   {collection}")
    print(f"patients:     {report.patients}")
    print(
        f"documents:    {report.resource_documents} resources, {report.summary_documents} summaries"
    )
    print(
        f"index:        {report.inserted} inserted, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.removed} removed"
    )
    print(f"total in index: {index.count()}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
