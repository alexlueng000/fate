import json
import pytest
from app.chat import deepseek_client as client


@pytest.mark.parametrize('ending,success', [('complete', True), ('disconnect', False), ('length', False)])
def test_paid_upstream_requires_a_complete_answer(monkeypatch, ending, success):
    monkeypatch.setattr(client, '_ensure_api_key', lambda: 'test')
    monkeypatch.setattr(client, '_write_prompt_log', lambda *_: None)
    monkeypatch.setattr(client, '_log_api_call', lambda **_: None)
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def raise_for_status(self): pass
        def iter_lines(self, **_):
            yield 'data: ' + json.dumps({'choices': [{'delta': {'content': '一部分回复'}}]})
            if ending != 'disconnect':
                yield 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop' if success else 'length'}]})
                yield 'data: [DONE]'
    monkeypatch.setattr(client.requests, 'post', lambda *_, **__: Response())
    stream = client.call_deepseek_stream([{'role': 'user', 'content': '问题'}], require_complete=True)
    if success:
        assert list(stream) == ['一部分回复']
    else:
        with pytest.raises(client.DeepSeekEmptyResponseError): list(stream)


@pytest.mark.parametrize('reason,success', [('stop', True), ('length', False), (None, False)])
def test_non_stream_report_must_be_complete(monkeypatch, reason, success):
    monkeypatch.setattr(client, '_ensure_api_key', lambda: 'test')
    monkeypatch.setattr(client, '_write_prompt_log', lambda *_: None)
    monkeypatch.setattr(client, '_log_api_call', lambda **_: None)
    monkeypatch.setattr(client, '_RETRY_TIMES', 1)
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {'choices': [{'message': {'content': '报告正文'}, 'finish_reason': reason}]}
    monkeypatch.setattr(client.requests, 'post', lambda *_, **__: Response())
    if success:
        assert client.call_deepseek([], require_complete=True) == '报告正文'
    else:
        with pytest.raises(client.DeepSeekEmptyResponseError):
            client.call_deepseek([], require_complete=True)
