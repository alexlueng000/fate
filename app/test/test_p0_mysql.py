"""Opt-in integration checks against the disposable P0 MySQL container only."""
import asyncio
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def mysql_stats():
    url = os.environ.get('P0_MYSQL_TEST_URL')
    if not url:
        pytest.skip('P0_MYSQL_TEST_URL not set; disposable MySQL required')
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'fate_p0_acceptance'
    engine = create_engine(url)
    tables = ['messages', 'conversations', 'orders', 'feedbacks', 'users']
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, created_at DATETIME)'))
        conn.execute(text('CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER, created_at DATETIME)'))
        conn.execute(text('CREATE TABLE messages (id INTEGER PRIMARY KEY, user_id INTEGER, conversation_id INTEGER, role VARCHAR(20), content TEXT, created_at DATETIME, prompt_tokens INTEGER, completion_tokens INTEGER)'))
        conn.execute(text('CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, status VARCHAR(20))'))
        conn.execute(text('CREATE TABLE feedbacks (id INTEGER PRIMARY KEY, status VARCHAR(20))'))
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            for table in tables:
                conn.execute(text(f'DROP TABLE {table}'))
        engine.dispose()


def test_mysql_stats_windows_and_deduplication(mysql_stats, monkeypatch):
    from app.routers import admin_stats
    # Shanghai 2026-09-17 00:00, with rows on both sides of midnight.
    monkeypatch.setattr(admin_stats, 'utc_now', lambda: datetime(2026, 9, 16, 16))
    with mysql_stats.begin() as conn:
        for uid, created in [(1, '2026-09-06 16:00:00'), (2, '2026-09-06 16:00:00'), (3, '2026-09-16 15:59:59'), (4, '2026-09-16 16:00:00'), (5, '2026-09-16 16:00:01')]:
            conn.execute(text('INSERT INTO users VALUES (:id, :created)'), dict(id=uid, created=created))
            conn.execute(text('INSERT INTO conversations VALUES (:id, :id, :created)'), dict(id=uid, created=created))
        rows = [
            (1, 1, 'user', 'initial', '2026-09-06 16:00:00'),
            (2, 1, 'assistant', 'not a return', '2026-09-08 16:00:00'),
            (3, 1, 'user', '168h excluded', '2026-09-13 16:00:00'),
            (4, 2, 'user', '24h included', '2026-09-07 16:00:00'),
            (5, 2, 'user', 'active', '2026-09-15 16:00:00'),
            (6, 2, 'user', 'duplicate user', '2026-09-16 15:00:00'),
            (7, 3, 'user', '   ', '2026-09-16 16:00:00'),
            (8, 4, 'assistant', 'not active', '2026-09-16 16:00:00'),
        ]
        for mid, uid, role, content, created in rows:
            conn.execute(text('INSERT INTO messages VALUES (:mid, :uid, :uid, :role, :content, :created, 0, 0)'), dict(mid=mid, uid=uid, role=role, content=content, created=created))
        conn.execute(text("INSERT INTO orders VALUES (1, 1, 'PAID'), (2, 1, 'PAID'), (3, 2, 'CREATED')"))
    with Session(mysql_stats) as db:
        overview = asyncio.run(admin_stats.get_overview(db=db, _admin=None))
        assert overview['users']['today'] == 1
        assert overview['users']['active_7d'] == 2
        assert overview['rates']['retention_7d'] == 50
        assert overview['rates']['samples']['paid_users'] == 1
        assert overview['rates']['samples']['retention_cohort'] == 2
        for endpoint in (admin_stats.get_users_trend, admin_stats.get_conversations_trend):
            data = asyncio.run(endpoint(period='7d', db=db, _admin=None))['data']
            assert len(data) == 7
            assert data[0] == {'date': '2026-09-11', 'count': 0}
            assert data[-2] == {'date': '2026-09-16', 'count': 1}
            assert data[-1] == {'date': '2026-09-17', 'count': 1}


def test_mysql_empty_samples(mysql_stats):
    from app.routers import admin_stats
    with Session(mysql_stats) as db:
        result = asyncio.run(admin_stats.get_overview(db=db, _admin=None))
    assert result['users']['total'] == 0
    for key in ('new_user_activation', 'first_read_followup', 'retention_7d', 'paid_conversion'):
        assert result['rates'][key] == 0
    assert all(value == 0 for value in result['rates']['samples'].values())
