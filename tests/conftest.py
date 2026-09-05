import pytest_asyncio

from connector import TelegramConnector


@pytest_asyncio.fixture()
async def tg():
    async with TelegramConnector() as conn:
        yield conn
