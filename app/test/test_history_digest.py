"""SQLite regression coverage; no live DB or model API is contacted."""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text, select, event
from sqlalchemy.orm import sessionmaker
from fastapi import BackgroundTasks, HTTPException
from app.models.chat import Conversation, Message
from app.models.conversation_digest import ConversationDigest
from app.routers.conversations import (
    list_conversations, get_digest, request_digest, rename_conversation,
    delete_conversation, DigestRequest, RenameRequest,
)
from app.services.conversation_digest import generate_digest, DigestOutput, build_source


class HistoryDigestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE user_profiles (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE liuyao_hexagrams (id INTEGER PRIMARY KEY)'))
            conn.execute(text('INSERT INTO users VALUES (1), (2)'))
            conn.execute(text('INSERT INTO user_profiles VALUES (1)'))
            conn.execute(text('CREATE TABLE app_config (cfg_key TEXT, value_json TEXT, is_active INTEGER, version INTEGER)'))
            conn.execute(text('INSERT INTO app_config VALUES (:key, :value, 1, 1)'), {'key': 'history_digest_prompt', 'value': json.dumps({'content': 'test prompt'})})
        Conversation.__table__.create(self.engine)
        Message.__table__.create(self.engine)
        ConversationDigest.__table__.create(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.conv = Conversation(id=1, user_id=1, profile_id=1, title='八字解读', updated_at=datetime(2026, 8, 1))
        self.db.add(self.conv)
        self.db.flush()
        self.db.add_all([Message(id=1, conversation_id=1, user_id=1, role='user', content='今年换工作合适吗？'), Message(id=2, conversation_id=1, user_id=1, role='assistant', content='当时建议核对工作机会与收入。')])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def listing(self, query='', user=1):
        return list_conversations(type='bazi', limit=20, offset=0, q=query, db=self.db, user_id=user)

    def test_search_ownership_and_fallback_title(self):
        self.assertEqual(self.listing('工作').total, 1)
        self.assertEqual(self.listing('%').total, 0)
        self.assertEqual(self.listing(user=2).total, 0)
        self.assertEqual(self.listing().items[0].title, '今年换工作合适吗？')
        for fn in [get_digest, delete_conversation]:
            with self.assertRaises(HTTPException) as error:
                fn(1, db=self.db, user_id=2)
            self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            rename_conversation(1, RenameRequest(title='越权'), db=self.db, user_id=2)
        with self.assertRaises(HTTPException):
            request_digest(1, DigestRequest(), BackgroundTasks(), db=self.db, user_id=2)

    def test_duplicate_request_and_title_preserved(self):
        tasks = BackgroundTasks()
        request_digest(1, DigestRequest(), tasks, db=self.db, user_id=1)
        request_digest(1, DigestRequest(), tasks, db=self.db, user_id=1)
        self.assertEqual(len(tasks.tasks), 1)
        rename_conversation(1, RenameRequest(title='我的事业选择'), db=self.db, user_id=1)
        token = self.db.get(ConversationDigest, 1).request_token
        response = MagicMock()
        response.json.return_value = {'choices': [{'message': {'content': json.dumps({'title': 'AI的标题', 'topic': 'UNKNOWN', 'question': '是否换工作？', 'summary': '当时解读认为可以先了解机会。'})}}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 30}}
        with patch('app.services.conversation_digest.SessionLocal', self.sessions), patch('app.services.conversation_digest.settings.deepseek_api_key', 'test'), patch('app.services.conversation_digest.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value = response
            generate_digest(1, token)
        self.db.expire_all()
        digest = self.db.get(ConversationDigest, 1)
        self.assertEqual(digest.status, 'ready')
        self.assertEqual(digest.custom_title, '我的事业选择')
        self.assertEqual(digest.topic, 'OTHER')
        self.assertEqual(self.db.get(Conversation, 1).updated_at, datetime(2026, 8, 1))
        self.assertEqual(self.listing('我的事业').total, 1)
        tasks = BackgroundTasks()
        request_digest(1, DigestRequest(), tasks, db=self.db, user_id=1)
        self.assertEqual(len(tasks.tasks), 0)
        self.db.add(Message(id=3, user_id=1, conversation_id=1, role='assistant', content='补充的新解读'))
        self.db.commit()
        self.assertTrue(get_digest(1, db=self.db, user_id=1).stale)

    def test_failure_keeps_existing_summary_and_stale_lease_recovers(self):
        digest = ConversationDigest(conversation_id=1, status='pending', summary='原来的摘要', request_token='lease', requested_at=datetime.utcnow() - timedelta(minutes=3), source_message_id=1)
        self.db.add(digest); self.db.commit()
        self.assertEqual(get_digest(1, db=self.db, user_id=1).status, 'failed')
        with patch('app.services.conversation_digest.SessionLocal', self.sessions), patch('app.services.conversation_digest.settings.deepseek_api_key', None):
            generate_digest(1, 'lease')
        self.db.expire_all()
        self.assertEqual(self.db.get(ConversationDigest, 1).summary, '原来的摘要')
        tasks = BackgroundTasks()
        request_digest(1, DigestRequest(refresh=True), tasks, db=self.db, user_id=1)
        self.assertEqual(len(tasks.tasks), 1)

    def test_delete_cascades_and_delayed_job_does_not_recreate(self):
        request_digest(1, DigestRequest(), BackgroundTasks(), db=self.db, user_id=1)
        token = self.db.get(ConversationDigest, 1).request_token
        delete_conversation(1, db=self.db, user_id=1)
        with self.sessions() as session:
            self.assertIsNone(session.get(ConversationDigest, 1))
            self.assertEqual(len(session.scalars(select(Message)).all()), 0)
        with patch('app.services.conversation_digest.SessionLocal', self.sessions), patch('app.services.conversation_digest.settings.deepseek_api_key', 'test'), patch('app.services.conversation_digest.httpx.Client') as client:
            generate_digest(1, token)
            client.assert_not_called()

    def test_source_bound_and_output_validation(self):
        messages = [Message(id=i, role='assistant', content='字' * 10000) for i in range(1, 6)]
        source, covered = build_source(messages)
        self.assertLessEqual(sum(len(row['content']) for row in source), 24000)
        self.assertEqual(covered, 5)
        with self.assertRaises(ValueError):
            DigestOutput(title=' ', topic='OTHER', question='问题', summary='摘要')


if __name__ == '__main__':
    unittest.main()
