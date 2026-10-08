"""Report evidence reaches the provider; admin rebuilds the same searchable index."""
from pathlib import Path

from app.chat import service, utils, rag
from app.services.conversation_report import PERSONAL_TITLES, report_sections

CHART = {
    'gender': '女', 'solar_date': '1993-03-09 07:00:00',
    'four_pillars': {'year': ['癸', '酉'], 'month': ['乙', '卯'],
                     'day': ['己', '丑'], 'hour': ['丁', '卯']},
    'dayun': [{'age': 8, 'start_year': 2025, 'pillar': ['辛', '亥']}],
}
ANSWER = '\n\n'.join(f'### {title}\n\n完整分析内容。' for title in PERSONAL_TITLES)


def test_zero_setting_still_retrieves_topic_evidence_for_report(monkeypatch):
    queries, submitted = [], []
    def retrieve(query, index_dir, k):
        queries.append(query)
        return ['【共同依据】共同材料', f'【专题依据】{query.splitlines()[0]}']
    monkeypatch.setattr(service, 'retrieve_kb', retrieve)
    monkeypatch.setattr(utils, 'load_report_system_prompt_from_db', lambda: '管理员的报告角色说明')
    monkeypatch.setattr(service, 'should_stream', lambda _: False)
    monkeypatch.setattr(service, 'set_conv', lambda *a, **kw: None)
    monkeypatch.setattr(service, 'append_history', lambda *a, **kw: None)
    def provider(messages, **kwargs):
        submitted.extend(messages)
        return ANSWER
    monkeypatch.setattr(service, 'call_deepseek', provider)
    _, reply = service.start_chat(CHART, '/test/bazi', 0, None)
    assert [section['title'] for section in report_sections(reply)] == PERSONAL_TITLES
    assert len(queries) == 4 and all('日柱: 己丑' in q for q in queries)
    system, request = submitted
    assert '管理员的报告角色说明' in system['content']
    assert system['content'].count('【共同依据】') == 1
    assert all(q.splitlines()[0] in system['content'] for q in queries)
    assert 'SUGGESTED_QUESTIONS' not in system['content']
    assert '命盘依据—作用关系—倾向判断—现实建议' in request['content']
    assert all(f'### {title}' in request['content'] for title in PERSONAL_TITLES)


def test_topic_failure_preserves_other_evidence(monkeypatch):
    def retrieve(query, index_dir, k):
        if '日主 月令' in query:
            raise RuntimeError('temporary retrieval failure')
        return [query.splitlines()[0]]
    monkeypatch.setattr(service, 'retrieve_kb', retrieve)
    assert len(service.retrieve_report_kb(CHART, '/test/bazi')) == 3


def test_admin_rebuild_indexes_word_and_uses_saved_tfidf(monkeypatch, tmp_path):
    from docx import Document
    from app.services import kb
    files, index = tmp_path / 'files', tmp_path / 'index'
    files.mkdir()
    (files / '事业.txt').write_text('career opportunity planning', encoding='utf-8')
    doc = Document()
    doc.add_paragraph('relationship marriage communication')
    doc.save(files / '感情.docx')
    monkeypatch.setattr(kb, 'KB_FILES_DIR', str(files))
    monkeypatch.setattr(kb, 'KB_INDEX_DIR', str(index))
    monkeypatch.setattr(kb, 'CHUNKS_JSON', str(index / 'chunks.json'))
    monkeypatch.setattr(kb, 'EMB_NPZ', str(index / 'embeddings.npz'))
    meta = kb.rebuild_index(backend='tfidf')
    assert meta['num_chunks'] == 2
    assert (index / 'tfidf_vectorizer.joblib').is_file()
    assert '感情.docx' in rag.retrieve_kb('relationship marriage', str(index))[0]
    assert kb.query_kb('relationship', 1)[0]['file'] == '感情.docx'


def test_admin_and_chat_share_bazi_index_and_legacy_override(monkeypatch, tmp_path):
    from app.services import kb
    assert Path(kb.KB_INDEX_DIR) == Path(rag.resolve_index_dir('bazi'))
    monkeypatch.delenv('KB_BAZI_INDEX_DIR', raising=False)
    monkeypatch.setenv('KB_INDEX_DIR', str(tmp_path / 'existing-index'))
    assert rag.resolve_index_dir('bazi') == str(tmp_path / 'existing-index')
    monkeypatch.setenv('KB_BAZI_INDEX_DIR', str(tmp_path / 'typed-index'))
    assert rag.resolve_index_dir('bazi') == str(tmp_path / 'typed-index')


def test_regeneration_upgrades_old_report_request(monkeypatch):
    captured = []
    conv = {'history': [{'role': 'user', 'content': '我的命盘信息如下：旧版通用解读'},
                        {'role': 'assistant', 'content': ANSWER}], 'paipan': CHART}
    monkeypatch.setattr(service, 'get_conv', lambda _: conv)
    monkeypatch.setattr(service, 'retrieve_kb', lambda *args, **kwargs: ['【依据】日主旺衰'])
    monkeypatch.setattr(utils, 'load_report_system_prompt_from_db', lambda: '管理员报告配置')
    monkeypatch.setattr(service, 'set_conv', lambda *a, **kw: None)
    def provider(messages, **kwargs):
        captured.extend(messages)
        return ANSWER
    monkeypatch.setattr(service, 'call_deepseek', provider)
    service.regenerate('bazi_conv_test')
    assert '【依据】日主旺衰' in captured[0]['content']
    assert '命盘依据—作用关系—倾向判断—现实建议' in captured[-1]['content']
    assert '旧版通用解读' not in captured[-1]['content']


def test_prompt_loader_respects_admin_active_version():
    from sqlalchemy import create_engine, text
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE app_config (cfg_key TEXT, version INTEGER, value_json TEXT, is_active INTEGER)'))
        db.execute(text('INSERT INTO app_config VALUES (:key, :version, :value, :active)'), [
            {'key': 'report_system_prompt', 'version': 1, 'value': '{"content": "active analysis"}', 'active': 1},
            {'key': 'report_system_prompt', 'version': 2, 'value': '{"content": "inactive simplified"}', 'active': 0},
        ])
        selected = utils.fetch_latest_config(db, 'report_system_prompt')
        assert selected['version'] == 1
        assert selected['value_json']['content'] == 'active analysis'
    engine.dispose()


def test_legacy_shared_index_is_used_only_for_bazi(monkeypatch, tmp_path):
    monkeypatch.delenv('KB_BAZI_INDEX_DIR', raising=False)
    monkeypatch.delenv('KB_LIUYAO_INDEX_DIR', raising=False)
    monkeypatch.delenv('KB_INDEX_DIR', raising=False)
    monkeypatch.setattr(rag, '__file__', str(tmp_path / 'app' / 'chat' / 'rag.py'))
    shared = tmp_path / 'kb_index'
    shared.mkdir()
    (shared / 'chunks.json').write_text('[]')
    assert rag.resolve_index_dir('bazi') == str(shared)
    assert rag.resolve_index_dir('liuyao') == str(shared / 'liuyao')
    typed = shared / 'bazi'
    typed.mkdir()
    (typed / 'chunks.json').write_text('[]')
    assert rag.resolve_index_dir('bazi') == str(typed)


def test_websocket_start_and_followup_use_current_prompts(monkeypatch):
    import asyncio
    import json
    from app.routers.chat import websocket_chat
    from app.chat import deepseek_client, store
    captured = []
    monkeypatch.setattr(utils, 'load_report_system_prompt_from_db', lambda: '启用的报告配置')
    monkeypatch.setattr(utils, 'load_system_prompt_from_db', lambda: '启用的聊天配置')
    monkeypatch.setattr(service, 'retrieve_kb', lambda *a, **kw: ['【依据】命盘分析材料'])
    monkeypatch.setattr(rag, 'retrieve_kb', lambda *a, **kw: ['【依据】命盘分析材料'])
    monkeypatch.setattr(store, 'set_conv', lambda *a, **kw: None)
    monkeypatch.setattr(store, 'append_history', lambda *a, **kw: None)
    monkeypatch.setattr(store, 'get_conv', lambda _: {
        'pinned': '已经停用的缓存配置', 'paipan': CHART, 'history': [],
    })
    def provider(messages, **kwargs):
        captured.append(messages)
        yield ANSWER
    monkeypatch.setattr(deepseek_client, 'call_deepseek_stream', provider)
    class Socket:
        def __init__(self, payload): self.payload = payload
        async def accept(self): pass
        async def receive_text(self): return json.dumps(self.payload)
        async def send_json(self, payload): pass
        async def send_text(self, payload): pass
        async def close(self): pass
    asyncio.run(websocket_chat(Socket({'action': 'start', 'paipan': CHART, 'kb_topk': 0})))
    asyncio.run(websocket_chat(Socket({'action': 'send', 'conversation_id': 'test', 'message': '请分析今年事业'})))
    assert len(captured) == 2
    assert '启用的报告配置' in captured[0][0]['content']
    assert '【依据】命盘分析材料' in captured[0][0]['content']
    assert '命盘依据—作用关系—倾向判断—现实建议' in captured[0][-1]['content']
    assert '启用的聊天配置' in captured[1][0]['content']
    assert '已经停用的缓存配置' not in captured[1][0]['content']
