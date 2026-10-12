from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from .config import Settings
from .schemas import EditPlan
from .server import build_server


def create_app(settings: Settings | None = None):
    mcp, store, ollama = build_server(settings)
    token = secrets.token_urlsafe(32)
    token_path = store.internal / "http-token"
    store.atomic_write(token_path, token.encode())
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    async def body(request: Request, limit=32 * 1024 * 1024):
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > limit:
                raise ValueError("Request is too large")
        return bytes(chunks)

    async def index(request):
        html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__WORD_TOKEN__", token), headers={"Cache-Control": "no-store"})

    async def health(request):
        return JSONResponse({"ok": True, "service": "offline-word-mcp", "version": "0.1.0"})

    async def api(request):
        action = request.path_params["action"]
        data = {}
        if request.method == "POST":
            data = json.loads(await body(request, 1024 * 1024))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
        query = request.query_params
        if action == "status":
            try:
                return JSONResponse(await run_in_threadpool(ollama.status))
            except ValueError as exc:
                return JSONResponse({"error": str(exc), "profile": store.settings.profile,
                                     "text_model": store.settings.text_model, "models": []})
        if action == "documents":
            result = await run_in_threadpool(store.list_documents)
        elif action == "read":
            result = await run_in_threadpool(store.snapshot, query["path"])
        elif action == "create":
            result = await run_in_threadpool(store.create, data["path"], data.get("title", ""))
        elif action == "propose":
            result = await run_in_threadpool(ollama.propose, store, data["path"], data["instruction"],
                                            data.get("targets"), data.get("model"))
        elif action == "apply":
            result = await run_in_threadpool(store.apply_proposal, data["proposal_id"])
        elif action == "manual":
            plan = EditPlan.model_validate(data["plan"])
            result = await run_in_threadpool(store.edit, data["path"], data["revision"], plan)
        elif action == "backups":
            result = await run_in_threadpool(store.backups, query["path"])
        elif action == "restore":
            result = await run_in_threadpool(store.restore, data["path"], data["backup_id"], data["revision"])
        elif action == "analyze":
            result = await run_in_threadpool(ollama.analyze, store, data["path"], data["image_id"],
                                            data.get("question", "Опиши изображение, прочитай текст и предложи подпись на русском."),
                                            data.get("model"))
        else:
            return JSONResponse({"error": "Unknown action"}, status_code=404)
        return JSONResponse(result)

    async def upload(request):
        filename = request.query_params.get("name", "document.docx")
        data = await body(request)
        if request.path_params["kind"] == "document":
            name = Path(filename.replace("\\", "/")).name
            result = await run_in_threadpool(store.import_document, name, data)
        elif request.path_params["kind"] == "image":
            result = await run_in_threadpool(store.save_asset, filename, data)
        else:
            raise ValueError("Unsupported upload type")
        return JSONResponse(result)

    async def download(request):
        name = request.query_params["path"]
        _, data, _ = await run_in_threadpool(store.load, name)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    async def image(request):
        data = await run_in_threadpool(store.image, request.query_params["path"], request.query_params["id"], True)
        return Response(data, media_type="image/png")

    async def handle_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=422)

    app = Starlette(routes=[
        Route("/", index), Route("/health", health),
        Route("/api/{action}", api, methods=["GET", "POST"]),
        Route("/upload/{kind}", upload, methods=["POST"]),
        Route("/download", download), Route("/image", image),
        Mount("/mcp", app=mcp_app),
    ], lifespan=lifespan, exception_handlers={
        ValueError: handle_error, FileNotFoundError: handle_error,
        PermissionError: handle_error, KeyError: handle_error, ValidationError: handle_error,
    })

    class LocalOnly:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.inner(scope, receive, send)
            headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            host = headers.get("host", "")
            hostname = urlparse("http://" + host).hostname
            origin = headers.get("origin")
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                return await JSONResponse({"error": "Loopback access only"}, status_code=403)(scope, receive, send)
            if origin and origin != "http://" + host:
                return await JSONResponse({"error": "Origin rejected"}, status_code=403)(scope, receive, send)
            if scope["path"] not in ("/", "/health"):
                supplied = headers.get("x-word-token", "")
                if headers.get("authorization", "").startswith("Bearer "):
                    supplied = headers["authorization"][7:]
                if not secrets.compare_digest(supplied, token):
                    return await JSONResponse({"error": "Local session token required"}, status_code=401)(scope, receive, send)
            return await self.inner(scope, receive, send)

    return LocalOnly(app)
