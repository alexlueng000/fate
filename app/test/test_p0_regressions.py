"""P0 display, metrics and calendar regressions; no external services."""
from datetime import datetime, timedelta

import pytest

from app.services.stats_windows import calendar_window, is_return_visit


def test_shanghai_day_bounds_and_exact_calendar_day_count():
    # UTC 16:00 is the start of the next Shanghai date.
    now = datetime(2026, 9, 15, 16, 0)
    assert calendar_window(now, 1) == (now, now + timedelta(days=1))
    start, end = calendar_window(now, 30)
    assert end - start == timedelta(days=30)
    assert start == datetime(2026, 8, 17, 16)


@pytest.mark.parametrize("hours,expected", [(23.99, False), (24, True), (167.99, True), (168, False), (180, False)])
def test_retention_boundary(hours, expected):
    registered = datetime(2026, 8, 1)
    assert is_return_visit(registered, registered + timedelta(hours=hours)) == expected


def test_preview_strips_formatting_without_mutating_message():
    from app.routers.conversations import _preview, _safe_user_message, _four_pillars_summary
    source = '### 核心判断\n**先核对条件**，再看[说明](https://example.com)。'
    assert _preview(source) == '核心判断 先核对条件，再看说明。'
    assert source.startswith('###')
    prompt = '请基于以下卦象做第一次解读：\n\n- 所问之事：这个机会值得争取吗？\n希望三个月内确定。\n- 性别：男\n- 本卦：地泽临'
    assert _safe_user_message(prompt) == '这个机会值得争取吗？\n希望三个月内确定。'
    assert _safe_user_message('请基于以下卦象做第一次解读：缺少问题') is None
    assert _four_pillars_summary({'four_pillars': {'year': ['癸', '酉'], 'month': '乙卯', 'day': {'stem': '己', 'branch': '丑'}, 'hour': ['丁', '卯']}}) == '癸酉·乙卯·己丑·丁卯'


@pytest.mark.parametrize('year,month,day,leap', [(1993, 2, 17, False), (2023, 2, 1, True)])
def test_lunar_and_solar_inputs_match_after_cross_day_correction(year, month, day, leap):
    from lunar_python import Lunar
    from app.bazi_engine import BirthInput, build_chart
    from app.routers.bazi import PaipanIn, calc_bazi
    solar = Lunar.fromYmdHms(year, -month if leap else month, day, 0, 10, 0).getSolar()
    solar_date = solar.toYmd()
    lunar_date = f'{year:04}-{month:02}-{day:02}'
    common = dict(gender='男', birth_time='00:10', birthplace='测试', longitude=105)
    lunar_result = calc_bazi(PaipanIn(**common, calendar='lunar', birth_date=lunar_date, leap_month=leap))
    solar_result = calc_bazi(PaipanIn(**common, birth_date=solar_date))
    assert 'error' not in lunar_result
    assert lunar_result == solar_result
    expected = datetime.fromisoformat(solar.toYmdHms()) - timedelta(hours=1)
    assert lunar_result['mingpan']['solar_date'] == expected.strftime('%Y-%m-%d %H:%M:%S')
    lunar_chart = build_chart(BirthInput(calendar='lunar', local_datetime=lunar_date + ' 00:10:00', leap_month=leap, longitude=105), '男')
    solar_chart = build_chart(BirthInput(local_datetime=solar.toYmdHms(), longitude=105), '男')
    assert lunar_chart.four_pillars == solar_chart.four_pillars
    assert lunar_chart.adjusted_datetime == expected
    assert lunar_chart.dayun == solar_chart.dayun


def test_lunar_day_not_valid_in_gregorian_calendar_is_accepted_by_router():
    from app.routers.bazi import PaipanIn, calc_bazi
    result = calc_bazi(PaipanIn(gender='男', calendar='lunar', birth_date='2023-02-30', birth_time='12:00', birthplace='测试', use_true_solar=False))
    assert 'error' not in result
    assert result['mingpan']['solar_date'].startswith('2023-03-21')


def test_geocoding_fallback_is_reported(monkeypatch):
    from app.routers import bazi
    monkeypatch.setattr(bazi.geo_amap, 'geocode_city', lambda _: {'error': 'unavailable'})
    result = bazi.calc_bazi(bazi.PaipanIn(gender='男', birth_date='1993-03-09', birth_time='07:30', birthplace='测试'))
    chart = result['mingpan']
    assert chart['time_correction_method'] == 'none'
    assert chart['warnings']
    assert chart['solar_date'] == '1993-03-09 07:30:00'


def test_overview_counts_messages_not_logins_and_excludes_late_returns(monkeypatch):
    import asyncio
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.routers import admin_stats
    now = datetime(2026, 9, 16, 2)
    monkeypatch.setattr(admin_stats, 'utc_now', lambda: now)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        for statement in (
            'CREATE TABLE users (id INTEGER PRIMARY KEY, created_at DATETIME)',
            'CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER, created_at DATETIME)',
            'CREATE TABLE messages (id INTEGER PRIMARY KEY, user_id INTEGER, conversation_id INTEGER, role TEXT, content TEXT, created_at DATETIME, prompt_tokens INTEGER, completion_tokens INTEGER)',
            'CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT)',
            'CREATE TABLE feedbacks (id INTEGER PRIMARY KEY, status TEXT)',
        ):
            connection.execute(text(statement))
        registered = now - timedelta(days=10)
        for uid, created in [(1, registered), (2, registered), (3, now - timedelta(hours=3))]:
            connection.execute(text('INSERT INTO users VALUES (:id, :created)'), {'id': uid, 'created': created})
            connection.execute(text('INSERT INTO conversations VALUES (:id, :id, :created)'), {'id': uid, 'created': created})
        rows = [
            (1, 1, 'user', 'first', registered),
            (2, 1, 'assistant', 'automatic', registered + timedelta(days=2)),
            (3, 1, 'user', 'too late', registered + timedelta(days=7, hours=1)),
            (4, 2, 'user', 'return', registered + timedelta(days=6)),
            (5, 2, 'user', '   ', registered + timedelta(days=6)),
            (6, 3, 'assistant', 'automatic', now - timedelta(hours=1)),
        ]
        for mid, uid, role, content, created in rows:
            connection.execute(text('INSERT INTO messages VALUES (:id, :uid, :uid, :role, :content, :created, 0, 0)'), dict(id=mid, uid=uid, role=role, content=content, created=created))
        connection.execute(text("INSERT INTO orders VALUES (1, 1, 'PAID'), (2, 1, 'PAID'), (3, 2, 'CREATED')"))
    with Session(engine) as session:
        result = asyncio.run(admin_stats.get_overview(db=session, _admin=None))
    assert result['users']['today'] == 1
    assert result['users']['active_7d'] == 2
    assert result['rates']['retention_7d'] == 50.0
    assert result['rates']['first_read_followup'] == 50.0
    assert result['rates']['samples']['retention_cohort'] == 2
    assert result['rates']['samples']['paid_users'] == 1
    assert result['rates']['paid_conversion'] == 33.33
    engine.dispose()


@pytest.mark.parametrize('endpoint', ['get_users_trend', 'get_conversations_trend'])
def test_trend_fills_missing_dates_and_compiles_shanghai_grouping(monkeypatch, endpoint):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from sqlalchemy.dialects import mysql
    from sqlalchemy.orm import Session
    from app.routers import admin_stats
    monkeypatch.setattr(admin_stats, 'utc_now', lambda: datetime(2026, 9, 15, 16))
    # Compile the real query through a session but never connect to a database.
    session = Session()
    captured = []

    def query(*entities):
        real = session.query(*entities)
        mock = MagicMock()
        def apply_filter(*conditions):
            nonlocal real
            real = real.filter(*conditions)
            return mock
        def group(*columns):
            nonlocal real
            real = real.group_by(*columns)
            return mock
        def order(*columns):
            nonlocal real
            real = real.order_by(*columns)
            captured.append(str(real.statement.compile(dialect=mysql.dialect(), compile_kwargs={'literal_binds': True})))
            return mock
        mock.filter.side_effect = apply_filter
        mock.group_by.side_effect = group
        mock.order_by.side_effect = order
        mock.all.return_value = [SimpleNamespace(date='2026-09-16', count=2)]
        return mock

    result = asyncio.run(getattr(admin_stats, endpoint)(period='7d', db=SimpleNamespace(query=query), _admin=None))
    assert len(result['data']) == 7
    assert result['data'][0] == {'date': '2026-09-10', 'count': 0}
    assert result['data'][-1] == {'date': '2026-09-16', 'count': 2}
    assert 'timestampadd(HOUR, 8,' in captured[0]
    assert '2026-09-09 16:00:00' in captured[0]
    session.close()
