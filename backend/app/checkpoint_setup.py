"""Initialize LangGraph checkpoint tables outside API processes."""

import asyncio

from app.config import settings
from app.checkpoints import checkpoint_context


async def setup_checkpoints() -> None:
    async with checkpoint_context(settings.checkpoint_db_url) as checkpointer:
        await checkpointer.setup()


if __name__ == "__main__":
    asyncio.run(setup_checkpoints())
