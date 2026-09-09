import pytest
import pytest_asyncio

import db
from connector import TelegramConnector


@pytest_asyncio.fixture(scope="session")
async def tg():
    async with TelegramConnector() as conn:
        yield conn


@pytest_asyncio.fixture(scope="session")
async def conn():
    c = await db.connect()
    try:
        yield c
    finally:
        await c.close()


def pytest_addoption(parser):
    parser.addoption("--force", action="store_true",
                     help="paksa hit Telegram, jangan jawab dari cache")


@pytest.fixture()
def force(request):
    return request.config.getoption("--force")
