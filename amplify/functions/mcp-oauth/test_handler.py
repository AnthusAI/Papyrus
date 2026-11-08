import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

folder = Path(__file__).parent
sys.path.insert(0, str(folder))
spec = importlib.util.spec_from_file_location('mcp_handler', folder / 'handler.py')
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


def test_invalid_token_and_storage_failure_are_distinct(monkeypatch):
    for key, value in {'MCP_ORIGIN': 'https://cms.example', 'MCP_GRANT_TABLE': 'table', 'MCP_KMS_KEY': 'key'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(handler.boto3, 'client', lambda service: Mock())
    store = Mock()
    monkeypatch.setattr(handler, 'DynamoGrantStore', lambda *args: store)
    request = {'operation': 'verify', 'token': 'bad.token', 'resource': 'https://cms.example/api/mcp'}
    assert handler.handler(request, None) == {'principal': None}
    store.get.assert_not_called()
    store.get.side_effect = RuntimeError('storage unavailable')
    request['token'] = 'a' * 43 + '.' + 'b' * 43
    with pytest.raises(RuntimeError, match='storage unavailable'):
        handler.handler(request, None)


def test_valid_request_does_not_mask_storage_type_or_key_errors(monkeypatch):
    for key, value in {'MCP_ORIGIN': 'https://cms.example', 'MCP_GRANT_TABLE': 'table', 'MCP_KMS_KEY': 'key'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(handler.boto3, 'client', lambda service: Mock())
    store = Mock()
    monkeypatch.setattr(handler, 'DynamoGrantStore', lambda *args: store)
    request = {'operation': 'refresh', 'token': 'a' * 43 + '.' + 'b' * 43, 'resource': 'https://cms.example/api/mcp', 'client': 'client'}
    for error in (TypeError('corrupt'), KeyError('corrupt')):
        store.get.side_effect = error
        with pytest.raises(type(error)): handler.handler(request, None)
    assert handler.handler({'operation': 'refresh'}, None) == {'error': 'invalid_request'}
