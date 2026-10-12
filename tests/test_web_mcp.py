import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.testclient import TestClient

from word_mcp.config import Settings
from word_mcp.web import create_app


def test_browser_edit_download_restore_and_origin_protection(tmp_path):
    app = create_app(Settings(root=tmp_path))
    token = (tmp_path / ".word_mcp" / "http-token").read_text()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/documents").status_code == 401
        assert client.get("/health", headers={"host": "evil.example"}).status_code == 403
        headers = {"X-Word-Token": token}
        assert client.post("/api/create", json={"path": "doc.docx"}, headers={**headers, "Origin": "http://evil.example"}).status_code == 403
        created = client.post("/api/create", json={"path": "doc.docx", "title": "Превет"}, headers=headers).json()
        before = client.get("/download?path=doc.docx", headers=headers).content
        result = client.post("/api/manual", headers=headers, json={"path": "doc.docx", "revision": created["revision"], "plan": {"summary": "Правка", "operations": [{"op": "replace_text", "target": "p0", "old": "Превет", "new": "Привет"}]}})
        assert result.status_code == 200, result.text
        assert client.get("/api/read?path=doc.docx", headers=headers).json()["paragraphs"][0]["text"] == "Привет"
        record = result.json()
        assert client.post("/api/restore", headers=headers, json={"path": "doc.docx", "revision": record["revision"], "backup_id": record["backup_id"]}).status_code == 200
        assert client.get("/download?path=doc.docx", headers=headers).content == before


def test_stdio_mcp_real_protocol(tmp_path):
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "word_mcp", "server"], env={**os.environ, "WORD_MCP_ROOT": str(tmp_path)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"create_document", "read_document", "propose_edit", "analyze_image", "apply_edit"} <= names
                created = await session.call_tool("create_document", {"path": "mcp.docx", "title": "MCP работает"})
                assert not created.isError
                result = await session.call_tool("read_document", {"path": "mcp.docx"})
                snapshot = result.structuredContent or json.loads(result.content[0].text)
                assert snapshot["paragraphs"][0]["text"] == "MCP работает"
                revision = snapshot["revision"]
                edited = await session.call_tool("apply_edit", {"path": "mcp.docx", "revision": revision, "plan": {"summary": "test", "operations": [{"op": "replace_text", "target": "p0", "old": "работает", "new": "проверен"}]}})
                assert not edited.isError
                output = edited.structuredContent or json.loads(edited.content[0].text)
                assert output["changes"][0]["after"] == "MCP проверен"
    asyncio.run(run())
