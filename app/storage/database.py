"""Short-lived PostgreSQL connections with pgvector registration."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row


class Database:
    """Small wrapper providing tenant-safe asynchronous PostgreSQL connections.
    """
    def __init__(self, database_url: str) -> None:
        """Store the PostgreSQL connection URL.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self.database_url = database_url

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[psycopg.AsyncConnection[dict[str, Any]]]:
        """Open and manage an asynchronous database connection.

        Yields:
            Result of the operation.
        """
        connection = await psycopg.AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
        )
        try:
            await register_vector_async(connection)
            async with connection:
                yield connection
        finally:
            if not connection.closed:
                await connection.close()
