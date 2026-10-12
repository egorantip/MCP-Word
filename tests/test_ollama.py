import json

import httpx
import pytest

from word_mcp.config import Settings
from word_mcp.documents import DocumentStore
from word_mcp.ollama_client import OllamaClient


def fake_ollama(cloud=False, response=None, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:2b", "size": 123, "remote_model": "remote" if cloud else None}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["vision", "thinking"]})
        return httpx.Response(200, json={"message": {"content": json.dumps(response or {"summary": "Исправлена опечатка", "operations": [{"op": "replace_text", "target": "p0", "old": "Превет", "new": "Привет"}]}, ensure_ascii=False)}})
    return httpx.MockTransport(handler)


def test_structured_proposal_and_generation_limits(tmp_path):
    settings = Settings(root=tmp_path)
    store = DocumentStore(settings)
    store.create("test.docx", "Превет")
    original = store.path("test.docx").read_bytes()
    calls = []
    client = OllamaClient(settings, fake_ollama(calls=calls))
    result = client.propose(store, "test.docx", "Исправь опечатку", ["p0"])
    assert result["changes"][0]["after"] == "Привет"
    assert store.path("test.docx").read_bytes() == original
    payload = json.loads(calls[-1].content)
    assert payload["format"]["type"] == "object"
    assert payload["think"] is False
    assert payload["keep_alive"] == "0s"
    assert payload["options"]["num_ctx"] == 4096


def test_cloud_models_blocked_before_inference(tmp_path):
    calls = []
    client = OllamaClient(Settings(root=tmp_path), fake_ollama(cloud=True, calls=calls))
    with pytest.raises(ValueError, match="Cloud"):
        client.generate("qwen3.5:2b", [], {})
    assert [request.url.path for request in calls] == ["/api/tags"]


@pytest.mark.parametrize("url", ["https://ollama.com", "http://example.com", "http://user:secret@localhost:11434"])
def test_remote_inference_blocked(tmp_path, url):
    with pytest.raises(ValueError, match="Offline"):
        OllamaClient(Settings(root=tmp_path, ollama_url=url))


def test_document_context_never_silently_truncated(tmp_path):
    settings = Settings(root=tmp_path)
    store = DocumentStore(settings)
    store.create("long.docx", "Текст " * 10000)
    calls = []
    client = OllamaClient(settings, fake_ollama(calls=calls))
    with pytest.raises(ValueError, match="context"):
        client.propose(store, "long.docx", "Исправь ошибки")
    assert calls == []


def test_unselected_targets_rejected(tmp_path):
    settings = Settings(root=tmp_path)
    store = DocumentStore(settings)
    store.create("test.docx", "Превет")
    client = OllamaClient(settings, fake_ollama(response={"summary": "Ошибка", "operations": [{"op": "replace_text", "target": "p999", "old": "Превет", "new": "Привет"}]}))
    with pytest.raises(ValueError, match="outside"):
        client.propose(store, "test.docx", "Исправь опечатку", ["p0"])
