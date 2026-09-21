import pytest

from database.connection import get_connection


@pytest.fixture
def db():
    connection = get_connection()

    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()