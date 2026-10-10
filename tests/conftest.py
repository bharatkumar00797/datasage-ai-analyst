import sqlite3

import pytest

from datasage.dataset import build_sample_db


@pytest.fixture
def conn() -> sqlite3.Connection:
    return build_sample_db()
