"""Explicit destructive maintenance commands."""

import argparse
import asyncio

from sqlalchemy import func, select

from app.db import async_session_factory, engine
from app.models import KnowledgeDocument
from app.services.knowledge import knowledge_storage, knowledge_vector_index


async def reset_knowledge() -> None:
    async with async_session_factory() as db:
        document_count = int((await db.execute(
            select(func.count(KnowledgeDocument.id))
        )).scalar_one())
    if document_count:
        raise RuntimeError(
            "Refusing to reset object/vector stores while knowledge documents exist"
        )
    await knowledge_storage.startup()
    await knowledge_storage.clear()
    try:
        await knowledge_vector_index.reset_collection()
    finally:
        await knowledge_vector_index.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="BizSage3 maintenance commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reset = subparsers.add_parser("reset-knowledge")
    reset.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Confirm deletion of every object and vector in the knowledge stores",
    )
    args = parser.parse_args()
    if args.command == "reset-knowledge":
        if not args.confirm_reset:
            parser.error("reset-knowledge requires --confirm-reset")
        asyncio.run(reset_knowledge())


if __name__ == "__main__":
    main()
