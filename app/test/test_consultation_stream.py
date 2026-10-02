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
