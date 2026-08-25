from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import pytest
import httpx
from anthropic import AsyncAnthropic
from fastapi.testclient import TestClient
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI
from PIL import Image

from app.config import Settings
from app.main import create_app


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="test-api-key",
        model_name="test-human",
        admin_username="admin",
        admin_password="test-password",
        session_secret="test-session-secret",
        database_path=tmp_path / "test.db",
        response_timeout_seconds=2,
        job_ttl_seconds=3600,
        cookie_secure=False,
        poll_interval_seconds=0.01,
    )


def login_admin(client: TestClient) -> None:
    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert login.status_code == 303


def test_async_human_job_round_trip(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        unauthorized = client.get("/v1/models")
        assert unauthorized.status_code == 401

        auth = {"Authorization": "Bearer test-api-key"}
        models = client.get("/v1/models", headers=auth)
        assert models.status_code == 200
        assert models.json()["data"][0]["id"] == "test-human"
        assert "vision" in models.json()["data"][0]["metadata"]["capabilities"]

        created = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "你怎么看这件事？"}],
            },
        )
        assert created.status_code == 202
        request_id = created.json()["id"]

        login_admin(client)
        detail = client.get(f"/admin/api/requests/{request_id}")
        assert detail.status_code == 200
        assert detail.json()["preview"] == "你怎么看这件事？"

        answered = client.post(
            f"/admin/requests/{request_id}/answer",
            data={"response_type": "text", "answer": "这是我作为真人给出的回答。"},
            follow_redirects=False,
        )
        assert answered.status_code == 303

        job = client.get(f"/v1/human/jobs/{request_id}", headers=auth)
        assert job.status_code == 200
        assert job.json()["status"] == "answered"
        assert (
            job.json()["response"]["choices"][0]["message"]["content"]
            == "这是我作为真人给出的回答。"
        )


def test_admin_queue_uses_lightweight_summaries_for_large_context(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        long_system = "系统运行说明。" * 6_000
        long_tool_output = json.dumps(
            {"result": "工具执行结果" * 5_000}, ensure_ascii=False
        )
        client_internal = (
            "<system-reminder>\nSessionStart hook additional context: "
            + "skill instructions " * 1_000
            + "\n</system-reminder>"
        )
        long_user = "请分析这次任务并给我三个明确建议，优先说结论。" + "补充背景" * 500
        request = app.state.database.create_request(
            request_id="req_large_context",
            model="test-human",
            messages=[
                {"role": "system", "content": long_system},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_large",
                            "type": "function",
                            "function": {"name": "inspect_repo", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_large", "content": long_tool_output},
                {"role": "user", "content": client_internal},
                {"role": "user", "content": long_user},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "inspect_repo",
                        "description": "读取仓库信息",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            mode="async",
            expires_at=int(time.time()) + 3_600,
            source="openai_responses",
        )
        assert len(request["preview"]) <= 89
        assert request["preview"].endswith("…")

        login_admin(client)
        listing = client.get("/admin/api/requests?filter=pending")
        assert listing.status_code == 200
        summary = next(
            item for item in listing.json()["items"] if item["id"] == request["id"]
        )
        assert "messages" not in summary
        assert "tools" not in summary
        assert "response" not in summary
        assert summary["message_count"] == 5
        assert summary["system_count"] == 1
        assert summary["tool_count"] == 3
        assert summary["context_chars"] > 50_000
        assert len(listing.content) < 5_000

        detail = client.get(f"/admin/api/requests/{request['id']}")
        assert detail.status_code == 200
        assert detail.json()["messages"] == [{"role": "user", "content": long_user}]
        assert detail.json()["client_internal_count"] == 1
        assert detail.json()["raw_loaded"] is False
        assert detail.json()["tools"][0]["function"]["name"] == "inspect_repo"

        raw = client.get(f"/admin/api/requests/{request['id']}/raw")
        assert raw.status_code == 200
        assert raw.json()["messages"][0]["content"] == long_system
        assert raw.json()["messages"][-2]["content"] == client_internal
        assert raw.json()["raw_loaded"] is True
        assert raw.headers.get("content-encoding") == "gzip"
        assert len(detail.content) < len(raw.content) * 0.6


def test_request_summary_extracts_real_prompt_and_classifies_background_work(
    tmp_path: Path,
) -> None:
    app = create_app(build_settings(tmp_path))
    envelope = """# Files mentioned by the user:

## screenshot.png: /tmp/screenshot.png

## My request:
帮我看看这个页面为什么会重复显示
<image name=[Image #1] path=\"/tmp/screenshot.png\">
</image>
"""

    with TestClient(app) as client:
        conversation = app.state.database.create_request(
            request_id="req_envelope",
            model="test-human",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": envelope},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                        },
                    ],
                }
            ],
            mode="async",
            expires_at=int(time.time()) + 3_600,
            source="openai_responses",
        )
        assert conversation["preview"] == "帮我看看这个页面为什么会重复显示"
        assert conversation["request_kind"] == "conversation"
        assert conversation["attachment_count"] == 1

        memory = app.state.database.create_request(
            request_id="req_memory",
            model="test-human",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analyze this rollout and produce JSON with `raw_memory`, "
                        "`rollout_summary`, and `rollout_slug`."
                    ),
                }
            ],
            mode="async",
            expires_at=int(time.time()) + 3_600,
            source="openai_responses",
        )
        assert memory["request_kind"] == "memory"

        login_admin(client)
        listing = client.get("/admin/api/requests?filter=all").json()["items"]
        summary = next(item for item in listing if item["id"] == "req_envelope")
        assert summary["preview"] == "帮我看看这个页面为什么会重复显示"
        assert summary["attachment_count"] == 1
        assert summary["request_kind"] == "conversation"


def test_existing_request_rows_backfill_short_summaries(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """
            CREATE TABLE human_requests (
                id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                status TEXT NOT NULL,
                answer TEXT,
                mode TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                answered_at INTEGER,
                expires_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO human_requests (
                id, model, messages_json, status, answer, mode,
                created_at, answered_at, expires_at
            ) VALUES (?, ?, ?, 'pending', NULL, 'async', ?, NULL, ?)
            """,
            (
                "req_before_summary_migration",
                "test-human",
                json.dumps(
                    [{"role": "user", "content": "迁移前留下的长问题" * 100}],
                    ensure_ascii=False,
                ),
                int(time.time()),
                int(time.time()) + 3_600,
            ),
        )

    app = create_app(settings)
    with TestClient(app) as client:
        login_admin(client)
        items = client.get("/admin/api/requests?filter=pending").json()["items"]
        summary = next(
            item for item in items if item["id"] == "req_before_summary_migration"
        )
        assert summary["preview"].startswith("迁移前留下的长问题")
        assert summary["preview"].endswith("…")
        assert summary["context_chars"] > 900
        assert summary["message_count"] == 1


def test_non_stream_request_uses_segmented_admin_composer(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        created = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "普通请求也要分段作答"}],
                "stream": False,
            },
        )
        request_id = created.json()["id"]
        login_admin(client)

        detail = client.get(f"/admin/api/requests/{request_id}").json()
        assert detail["stream_requested"] is False
        assert detail["stream_chunks"] == []
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        ).status_code == 422

        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "普通第一段，"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "普通第二段。"},
        ).status_code == 200
        finished = client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        )
        assert finished.status_code == 200
        assert finished.json()["status"] == "answered"
        assert finished.json()["stream_chunk_count"] == 2
        assert finished.json()["answer_source"] == "human_stream"

        job = client.get(f"/v1/human/jobs/{request_id}", headers=auth).json()
        assert job["response"]["choices"][0]["message"]["content"] == (
            "普通第一段，普通第二段。"
        )


def test_image_input_and_function_tool_call(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        created = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请看看这张图"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,iVBORw0KGgo="
                                },
                            },
                        ],
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "save_note",
                            "description": "保存一条笔记",
                            "parameters": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        },
                    }
                ],
            },
        )
        assert created.status_code == 202
        request_id = created.json()["id"]

        login_admin(client)
        detail = client.get(f"/admin/api/requests/{request_id}")
        assert detail.json()["preview"].startswith("请看看这张图")
        assert detail.json()["tools"][0]["function"]["name"] == "save_note"
        image_url = detail.json()["messages"][0]["content"][1]["image_url"]["url"]
        assert image_url == f"/admin/api/requests/{request_id}/attachments/0/1"
        image = client.get(image_url)
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content == b"\x89PNG\r\n\x1a\n"
        assert client.get(f"/admin/api/requests/{request_id}/raw").json()[
            "messages"
        ][0]["content"][1]["image_url"]["url"].startswith("data:image/png")

        answered = client.post(
            f"/admin/requests/{request_id}/answer",
            data={
                "response_type": "tool_call",
                "tool_name": "save_note",
                "tool_arguments": '{"text":"来自真人的笔记"}',
            },
            follow_redirects=False,
        )
        assert answered.status_code == 303

        job = client.get(f"/v1/human/jobs/{request_id}", headers=auth).json()
        choice = job["response"]["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        assert choice["message"]["tool_calls"][0]["function"]["name"] == "save_note"


def test_server_managed_conversation_keeps_context(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        conversation = client.post(
            "/v1/human/conversations", headers=auth
        ).json()
        conversation_id = conversation["id"]

        first = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "conversation_id": conversation_id,
                "messages": [{"role": "user", "content": "我叫小明。"}],
            },
        ).json()
        assert app.state.database.answer_request(
            first["id"],
            {"role": "assistant", "content": "你好，小明。"},
            "msg_assistant_1",
        )

        second = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "conversation_id": conversation_id,
                "messages": [{"role": "user", "content": "我叫什么？"}],
            },
        )
        assert second.status_code == 202
        stored = app.state.database.get_request(second.json()["id"])
        assert stored is not None
        assert [message["role"] for message in stored["messages"]] == [
            "user",
            "assistant",
            "user",
        ]
        assert stored["messages"][0]["content"] == "我叫小明。"


def test_public_chat_upload_and_context(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        chat_page = client.get("/chat")
        assert chat_page.status_code == 200
        assert "API Playground" in chat_page.text
        assert "有什么可以帮你" in chat_page.text
        assert "真人" not in chat_page.text
        assert 'data-prompt="' in chat_page.text
        conversation = client.post("/chat/api/conversations").json()
        conversation_id = conversation["id"]

        image_buffer = io.BytesIO()
        Image.new("RGB", (24, 24), color=(72, 112, 80)).save(
            image_buffer, format="PNG"
        )
        uploaded = client.post(
            "/chat/api/uploads",
            files={"image": ("sample.png", image_buffer.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 201
        image_url = uploaded.json()["url"]
        assert image_url.endswith(".webp")

        sent = client.post(
            f"/chat/api/conversations/{conversation_id}/messages",
            json={"text": "请记住这张图片", "image_urls": [image_url]},
        )
        assert sent.status_code == 202
        request_id = sent.json()["request_id"]

        login_admin(client)
        first_chunk = client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "我看到了，"},
        )
        assert first_chunk.status_code == 200
        live = client.get(
            f"/chat/api/conversations/{conversation_id}"
        ).json()
        assert live["pending"] is True
        assert live["live_response"]["content"] == "我看到了，"
        assert len(live["live_response"]["chunks"]) == 1

        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "也会记住上下文。"},
        ).status_code == 200
        answered = client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        )
        assert answered.status_code == 200

        current = client.get(
            f"/chat/api/conversations/{conversation_id}"
        ).json()
        assert current["pending"] is False
        assert current["live_response"] is None
        assert len(current["messages"]) == 2
        assert current["messages"][0]["content"][0]["type"] == "image_url"
        assert current["messages"][1]["content"] == "我看到了，也会记住上下文。"


def test_unknown_model_is_rejected(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        unknown = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "not-real",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert unknown.status_code == 404


def test_timeout_fallback_covers_sync_api_and_public_chat(tmp_path: Path) -> None:
    settings = replace(
        build_settings(tmp_path),
        response_timeout_seconds=0,
        timeout_fallback_text="肉身延迟，请稍后再试。",
    )
    app = create_app(settings)
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        completion = client.post(
            "/v1/chat/completions",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "同步超时测试"}],
            },
        )
        assert completion.status_code == 200
        assert completion.json()["choices"][0]["message"]["content"] == "肉身延迟，请稍后再试。"
        assert completion.json()["human_metadata"]["answer_source"] == "timeout_fallback"

        assert client.get("/chat").status_code == 200
        conversation_id = client.post("/chat/api/conversations").json()["id"]
        sent = client.post(
            f"/chat/api/conversations/{conversation_id}/messages",
            json={"text": "网页超时测试", "image_urls": []},
        )
        assert sent.status_code == 202
        conversation = client.get(
            f"/chat/api/conversations/{conversation_id}"
        ).json()
        assert conversation["pending"] is False
        assert conversation["messages"][-1]["role"] == "assistant"
        assert conversation["messages"][-1]["content"] == "肉身延迟，请稍后再试。"
        stored = app.state.database.get_request(sent.json()["request_id"])
        assert stored is not None
        assert stored["answer_source"] == "timeout_fallback"


def test_streaming_completion_waits_for_human_answer(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        login_admin(client)
        future = executor.submit(
            client.post,
            "/v1/chat/completions",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "流式测试"}],
                "stream": True,
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        stored = app.state.database.get_request(request_id)
        assert stored is not None
        assert stored["stream_requested"] is True

        premature_finish = client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        )
        assert premature_finish.status_code == 422

        first = client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "第一段，"},
        )
        assert first.status_code == 200
        assert first.json()["position"] == 1
        detail = client.get(f"/admin/api/requests/{request_id}").json()
        assert detail["stream_chunk_count"] == 1
        assert detail["stream_chunks"][0]["content"] == "第一段，"

        second = client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "第二段。"},
        )
        assert second.status_code == 200
        finished = client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        )
        assert finished.status_code == 200
        assert finished.json()["status"] == "answered"
        assert finished.json()["stream_chunk_count"] == 2
        assert finished.json()["answer_source"] == "human_stream"

        response = future.result(timeout=3)
        assert response.status_code == 200
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: {")
        ]
        assert {payload["id"] for payload in payloads} == {request_id}
        assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
        contents = [
            payload["choices"][0]["delta"]["content"]
            for payload in payloads
            if "content" in payload["choices"][0]["delta"]
        ]
        assert contents == ["第一段，", "第二段。"]
        assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
        assert response.text.rstrip().endswith("data: [DONE]")


def test_openai_responses_non_stream_supports_items_images_and_tools(
    tmp_path: Path,
) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            "/v1/responses",
            headers=auth,
            json={
                "model": "gpt-compatible-alias",
                "instructions": "保持诚实，也保持一点幽默。",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "看看这张图片"},
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,iVBORw0KGgo=",
                            },
                            {
                                "type": "input_file",
                                "filename": "说明书.pdf",
                                "file_data": "data:application/pdf;base64,JVBERi0xLjQ=",
                            },
                        ],
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "name": "save_note",
                        "description": "保存笔记",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ],
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert request_id.startswith("resp_")
        stored = app.state.database.get_request(request_id)
        assert stored is not None
        assert stored["source"] == "openai_responses"
        assert stored["model"] == "gpt-compatible-alias"
        assert stored["messages"][0]["role"] == "system"
        assert stored["messages"][1]["content"][1]["type"] == "image_url"
        assert stored["messages"][1]["content"][2]["type"] == "file"
        assert stored["messages"][1]["content"][2]["file"]["filename"] == "说明书.pdf"
        assert stored["attachment_count"] == 2
        assert stored["tools"][0]["function"]["name"] == "save_note"

        assert app.state.database.answer_request(
            request_id,
            {"role": "assistant", "content": "图我看到了，人类视觉模块正常。"},
            f"msg_answer_{request_id}",
        )
        response = future.result(timeout=3)
        assert response.status_code == 200
        assert response.headers["x-request-id"] == request_id
        body = response.json()
        assert body["id"] == request_id
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert body["output"][0]["type"] == "message"
        assert body["output"][0]["content"][0]["type"] == "output_text"
        assert body["output"][0]["content"][0]["text"] == (
            "图我看到了，人类视觉模块正常。"
        )


def test_openai_responses_stream_and_previous_response_context(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        login_admin(client)
        future = executor.submit(
            client.post,
            "/v1/responses",
            headers=auth,
            json={
                "model": "gpt-5",
                "input": "我的名字叫小明。",
                "stream": True,
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "你好，"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "小明。"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        ).status_code == 200

        streamed = future.result(timeout=3)
        assert streamed.status_code == 200
        event_names = [
            line.removeprefix("event: ")
            for line in streamed.text.splitlines()
            if line.startswith("event: ")
        ]
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: {")
        ]
        assert event_names[:2] == ["response.created", "response.in_progress"]
        assert event_names[-1] == "response.completed"
        deltas = [
            item["delta"]
            for item in payloads
            if item["type"] == "response.output_text.delta"
        ]
        assert deltas == ["你好，", "小明。"]
        assert payloads[-1]["response"]["output"][0]["content"][0]["text"] == (
            "你好，小明。"
        )

        followup = client.post(
            "/v1/responses",
            headers=auth,
            json={
                "model": "gpt-5",
                "input": "我叫什么？",
                "previous_response_id": request_id,
                "background": True,
            },
        )
        assert followup.status_code == 200
        assert followup.json()["status"] == "in_progress"
        followup_id = followup.json()["id"]
        chained = app.state.database.get_request(followup_id)
        assert chained is not None
        assert [message["role"] for message in chained["messages"]] == [
            "user",
            "assistant",
            "user",
        ]
        assert chained["messages"][1]["content"] == "你好，小明。"

        assert app.state.database.answer_request(
            followup_id,
            {"role": "assistant", "content": "你叫小明。"},
            f"msg_answer_{followup_id}",
        )
        retrieved = client.get(f"/v1/responses/{followup_id}", headers=auth)
        assert retrieved.status_code == 200
        assert retrieved.json()["status"] == "completed"
        assert retrieved.json()["output"][0]["content"][0]["text"] == "你叫小明。"


def test_anthropic_messages_supports_native_auth_blocks_and_tool_use(
    tmp_path: Path,
) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"x-api-key": "test-api-key", "anthropic-version": "2023-06-01"}
    long_tool_description = "Claude Code 工具说明。" * 300

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            "/v1/messages",
            headers=auth,
            json={
                "model": "claude-sonnet-compatible",
                "max_tokens": 1024,
                "system": [{"type": "text", "text": "你是一个真人模型。"}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "保存图片备注"},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "iVBORw0KGgo=",
                                },
                            },
                        ],
                    }
                ],
                "tools": [
                    {
                        "name": "save_note",
                        "description": long_tool_description,
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ],
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert request_id.startswith("msg_")
        stored = app.state.database.get_request(request_id)
        assert stored is not None
        assert stored["source"] == "anthropic_messages"
        assert stored["tools"][0]["function"]["description"] == long_tool_description
        assert stored["messages"][1]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )

        assert app.state.database.answer_request(
            request_id,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "toolu_human_note",
                        "type": "function",
                        "function": {
                            "name": "save_note",
                            "arguments": '{"text":"真人备注"}',
                        },
                    }
                ],
            },
            f"msg_answer_{request_id}",
        )
        response = future.result(timeout=3)
        assert response.status_code == 200
        assert response.headers["request-id"] == request_id
        body = response.json()
        assert body["type"] == "message"
        assert body["stop_reason"] == "tool_use"
        assert body["content"][0] == {
            "type": "tool_use",
            "id": "toolu_human_note",
            "name": "save_note",
            "input": {"text": "真人备注"},
        }


def test_anthropic_stream_count_tokens_and_error_shapes(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"x-api-key": "test-api-key"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        unauthorized = client.post(
            "/v1/messages",
            json={
                "model": "claude-test",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["type"] == "error"
        assert unauthorized.json()["error"]["type"] == "authentication_error"

        counted = client.post(
            "/v1/messages/count_tokens",
            headers=auth,
            json={
                "model": "claude-test",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hello world"}],
            },
        )
        assert counted.status_code == 200
        assert counted.json()["input_tokens"] > 0

        login_admin(client)
        future = executor.submit(
            client.post,
            "/v1/messages",
            headers=auth,
            json={
                "model": "claude-test",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "流式说句话"}],
                "stream": True,
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "碳基"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "流式输出"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        ).status_code == 200

        streamed = future.result(timeout=3)
        event_names = [
            line.removeprefix("event: ")
            for line in streamed.text.splitlines()
            if line.startswith("event: ")
        ]
        assert event_names[0] == "message_start"
        assert event_names[-1] == "message_stop"
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: {")
        ]
        deltas = [
            item["delta"]["text"]
            for item in payloads
            if item["type"] == "content_block_delta"
            and item["delta"]["type"] == "text_delta"
        ]
        assert deltas == ["碳基", "流式输出"]


def test_gemini_generate_content_supports_images_tools_and_native_auth(
    tmp_path: Path,
) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            "/v1beta/models/gemini-compatible:generateContent?key=test-api-key",
            json={
                "systemInstruction": {
                    "parts": [{"text": "这是一个真人驱动的 Gemini。"}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": "保存图片备注"},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": "iVBORw0KGgo=",
                                }
                            },
                        ],
                    }
                ],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "save_note",
                                "description": "保存笔记",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                },
                            }
                        ]
                    }
                ],
            },
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert request_id.startswith("gemini_")
        stored = app.state.database.get_request(request_id)
        assert stored is not None
        assert stored["source"] == "gemini_generate_content"
        assert stored["messages"][0]["role"] == "system"
        assert stored["messages"][1]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )
        assert stored["tools"][0]["function"]["name"] == "save_note"

        assert app.state.database.answer_request(
            request_id,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_save_note",
                        "type": "function",
                        "function": {
                            "name": "save_note",
                            "arguments": '{"text":"Gemini 真人备注"}',
                        },
                    }
                ],
            },
            f"msg_answer_{request_id}",
        )
        response = future.result(timeout=3)
        assert response.status_code == 200
        assert response.headers["x-goog-request-id"] == request_id
        body = response.json()
        assert body["responseId"] == request_id
        assert body["modelVersion"] == "gemini-compatible"
        assert body["candidates"][0]["content"]["parts"][0] == {
            "functionCall": {
                "name": "save_note",
                "args": {"text": "Gemini 真人备注"},
            }
        }


def test_gemini_stream_count_tokens_and_error_shape(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"x-goog-api-key": "test-api-key"}

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        unauthorized = client.post(
            "/v1beta/models/gemini-test:generateContent",
            json={"contents": [{"parts": [{"text": "hello"}]}]},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["status"] == "UNAUTHENTICATED"

        counted = client.post(
            "/v1beta/models/gemini-test:countTokens",
            headers=auth,
            json={"contents": [{"parts": [{"text": "hello world"}]}]},
        )
        assert counted.status_code == 200
        assert counted.json()["totalTokens"] > 0

        login_admin(client)
        future = executor.submit(
            client.post,
            "/v1beta/models/gemini-test:streamGenerateContent?alt=sse",
            headers=auth,
            json={"contents": [{"parts": [{"text": "Gemini 流式测试"}]}]},
        )
        request_id = None
        for _ in range(100):
            pending = app.state.database.list_requests(status="pending")
            if pending:
                request_id = pending[0]["id"]
                break
            time.sleep(0.01)
        assert request_id is not None
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "Gemini "},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "也由真人流式回答。"},
        ).status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/finish"
        ).status_code == 200

        streamed = future.result(timeout=3)
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: {")
        ]
        deltas = [
            item["candidates"][0]["content"]["parts"][0]["text"]
            for item in payloads[:-1]
        ]
        assert deltas == ["Gemini ", "也由真人流式回答。"]
        assert payloads[-1]["candidates"][0]["finishReason"] == "STOP"
        assert payloads[-1]["responseId"] == request_id


def test_unified_admin_and_automation_crud(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        login_admin(client)
        page = client.get("/admin")
        assert page.status_code == 200
        assert "API control plane" in page.text
        assert "接入指南" in page.text
        assert "服务设置" in page.text
        assert "当前运行参数" in page.text
        assert "模型配置" not in page.text
        assert "快捷话术" in page.text
        assert "自动回复规则" in page.text
        assert "空闲自动接单" in page.text

        chat_page = client.get("/chat")
        assert "正在生成回复" in chat_page.text
        assert "Playground 仅用于调试" in chat_page.text
        assert "真人" not in chat_page.text

        # Legacy pages receive a finite compatibility event instead of keeping
        # one SSE connection per browser tab indefinitely.
        events = client.get("/admin/events")
        assert events.status_code == 200
        assert "retry: 10000" in events.text
        assert "data:" in events.text

        quick = client.post(
            "/admin/api/quick-replies",
            json={"title": "测试话术", "content": "让我想想。", "category": "测试"},
        )
        assert quick.status_code == 201
        quick_id = quick.json()["id"]
        assert client.patch(
            f"/admin/api/quick-replies/{quick_id}", json={"active": False}
        ).json()["active"] is False

        rule = client.post(
            "/admin/api/auto-rules",
            json={
                "name": "测试接待",
                "rule_type": "keyword",
                "match_type": "exact",
                "pattern": "在吗测试",
                "response_text": "在，只是反射弧有点长。",
                "delay_seconds": 0,
                "priority": 500,
                "active": True,
            },
        )
        assert rule.status_code == 201
        assert rule.json()["active"] is True
        preview = client.post(
            "/admin/api/auto-rules/preview", json={"text": "在吗测试"}
        )
        assert preview.status_code == 200
        assert preview.json()["matched"] is True
        assert preview.json()["rule"]["name"] == "测试接待"
        assert client.post(
            "/admin/api/auto-rules/preview", json={"text": "完全不相关的问题"}
        ).json()["matched"] is False
        overview = client.get("/admin/api/overview").json()
        assert overview["active_rules"] == 1
        assert overview["notifications_enabled"] is False
        assert client.post("/admin/api/notifications/test").status_code == 409


def test_admin_claim_prevents_duplicate_human_answers(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}
    operator_a = "operator_test_alpha"
    operator_b = "operator_test_bravo"

    with TestClient(app) as client:
        created = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "只能有一个人回答"}],
            },
        ).json()
        request_id = created["id"]
        login_admin(client)

        claimed = client.post(
            f"/admin/api/requests/{request_id}/claim",
            json={"operator_id": operator_a},
        )
        assert claimed.status_code == 200
        assert claimed.json()["claim_active"] is True
        assert client.post(
            f"/admin/api/requests/{request_id}/claim",
            json={"operator_id": operator_b},
        ).status_code == 409
        assert client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "抢答失败", "operator_id": operator_b},
        ).status_code == 409

        first_chunk = client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "由 A 回答第一段。", "operator_id": operator_a},
        )
        assert first_chunk.status_code == 200
        assert client.post(
            f"/admin/api/requests/{request_id}/claim/release",
            json={"operator_id": operator_a},
        ).json()["released"] is True
        assert client.post(
            f"/admin/api/requests/{request_id}/claim",
            json={"operator_id": operator_b},
        ).status_code == 200
        finished = client.post(
            f"/admin/api/requests/{request_id}/stream/finish",
            json={"operator_id": operator_b},
        )
        assert finished.status_code == 200
        assert finished.json()["status"] == "answered"
        assert finished.json()["stream_chunk_count"] == 1


def test_stream_chunk_resets_idle_deadline_and_presence(tmp_path: Path) -> None:
    settings = replace(
        build_settings(tmp_path),
        stream_idle_timeout_seconds=60,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/chat").status_code == 200
        conversation_id = client.post("/chat/api/conversations").json()["id"]
        sent = client.post(
            f"/chat/api/conversations/{conversation_id}/messages",
            json={"text": "计时与在线状态", "image_urls": []},
        ).json()
        request_id = sent["request_id"]
        initial = app.state.database.get_request(request_id)
        assert initial is not None

        login_admin(client)
        chunk = client.post(
            f"/admin/api/requests/{request_id}/stream/chunks",
            json={"content": "第一段"},
        )
        assert chunk.status_code == 200
        assert chunk.json()["expires_at"] > initial["expires_at"]
        assert 58 <= chunk.json()["expires_at"] - int(time.time()) <= 60

        app.state.database.touch_client_connection(request_id)
        presence = client.get(
            f"/admin/api/requests/{request_id}/presence"
        ).json()
        assert presence["client_connected"] is True
        assert presence["client_last_seen_at"] is not None


def test_production_settings_reject_example_secrets(tmp_path: Path) -> None:
    unsafe = replace(
        build_settings(tmp_path),
        environment="production",
        api_key="human-local-demo-key",
        admin_password="change-this-local-password",
        session_secret="change-this-session-secret",
    )
    with pytest.raises(ValueError, match="unsafe example value"):
        unsafe.validate()

    safe = replace(
        unsafe,
        api_key="api_" + "a" * 40,
        admin_password="correct-horse-battery-staple",
        session_secret="b" * 64,
        public_base_url="https://human.example.com",
        cookie_secure=True,
    )
    safe.validate()


def test_new_request_posts_notification_webhook(tmp_path: Path) -> None:
    received: list[dict[str, object]] = []
    arrived = Event()

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()
            arrived.set()

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), WebhookHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = replace(
        build_settings(tmp_path),
        notification_webhook_url=(
            f"http://127.0.0.1:{server.server_address[1]}/notify"
        ),
        public_base_url="https://human.example.com",
    )
    app = create_app(settings)
    auth = {"Authorization": "Bearer test-api-key"}

    try:
        with TestClient(app) as client:
            created = client.post(
                "/v1/human/jobs",
                headers=auth,
                json={
                    "model": "test-human",
                    "messages": [{"role": "user", "content": "通知我来回答"}],
                },
            )
            assert created.status_code == 202
            assert arrived.wait(2)
            login_admin(client)
            tested = client.post("/admin/api/notifications/test")
            assert tested.status_code == 200
            for _ in range(100):
                if len(received) >= 2:
                    break
                time.sleep(0.01)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert len(received) == 2
    assert received[0]["event"] == "human_request.created"
    request_payload = received[0]["request"]
    assert isinstance(request_payload, dict)
    assert request_payload["preview"] == "通知我来回答"
    assert request_payload["admin_url"].startswith(
        "https://human.example.com/admin#inbox/"
    )
    assert received[1]["event"] == "human_request.notification_test"


def test_keyword_auto_reply_answers_new_job(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    auth = {"Authorization": "Bearer test-api-key"}

    with TestClient(app) as client:
        login_admin(client)
        created_rule = client.post(
            "/admin/api/auto-rules",
            json={
                "name": "在吗测试",
                "rule_type": "keyword",
                "match_type": "contains",
                "pattern": "暗号土豆",
                "response_text": "土豆收到，本人稍后上线。",
                "delay_seconds": 0,
                "priority": 999,
                "active": True,
            },
        )
        assert created_rule.status_code == 201

        job = client.post(
            "/v1/human/jobs",
            headers=auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "呼叫暗号土豆"}],
            },
        ).json()
        for _ in range(100):
            result = client.get(f"/v1/human/jobs/{job['id']}", headers=auth).json()
            if result["status"] == "answered":
                break
            time.sleep(0.01)
        assert result["status"] == "answered"
        assert result["response"]["choices"][0]["message"]["content"] == "土豆收到，本人稍后上线。"
        stored = app.state.database.get_request(job["id"])
        assert stored is not None
        assert stored["answer_source"] == "automation"


def test_schedule_rule_supports_overnight_window(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))
    with TestClient(app):
        rule = app.state.database.create_auto_reply_rule(
            {
                "name": "深夜充电",
                "rule_type": "schedule",
                "response_text": "本模型正在睡觉。",
                "start_time": "23:00",
                "end_time": "08:00",
                "days": list(range(7)),
                "delay_seconds": 0,
                "priority": 10,
                "active": True,
            }
        )
        matched = app.state.database.resolve_auto_reply(
            [{"role": "user", "content": "深夜打扰了"}],
            now=datetime(2026, 8, 21, 1, 30),
        )
        assert matched is not None
        assert matched["id"] == rule["id"]


def test_managed_api_key_lifecycle_and_protocol_auth(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        login_admin(client)
        dashboard = client.get("/admin")
        assert dashboard.status_code == 200
        assert "会话工作台" in dashboard.text
        assert "像用户一样阅读聊天" in dashboard.text
        assert "admin.js?v=20260825f" in dashboard.text
        assert 'data-panel="keys"' in dashboard.text
        assert 'data-panel="integration"' in dashboard.text
        assert "OPENAI BASE URL" in dashboard.text
        assert 'id="api-key-dialog"' in dashboard.text
        assert 'id="api-key-reveal-dialog"' in dashboard.text
        assert 'id="api-share-card"' in dashboard.text
        assert 'id="download-share-card"' in dashboard.text
        assert "包含完整 API Key，请私下分享" in dashboard.text
        created = client.post(
            "/admin/api/api-keys",
            json={
                "name": "朋友的万能接入钥匙",
                "rate_limit_per_minute": 100,
                "daily_limit": 1000,
                "max_concurrent": 1,
            },
        )
        assert created.status_code == 201
        secret = created.json()["key"]
        item = created.json()["item"]
        assert secret.startswith("sk-")
        assert "iamllm" not in secret.lower()
        assert secret not in json.dumps(item)
        assert "key_hash" not in item

        listed = client.get("/admin/api/api-keys")
        assert listed.status_code == 200
        assert secret not in listed.text
        managed = next(
            entry for entry in listed.json()["items"] if entry["id"] == item["id"]
        )
        assert managed["key_hint"].startswith("sk-")
        assert managed["managed"] is True

        with app.state.database._connect() as connection:
            stored = connection.execute(
                "SELECT key_hash, key_hint FROM api_keys WHERE id = ?", (item["id"],)
            ).fetchone()
        assert stored is not None
        assert stored["key_hash"] != secret
        assert secret not in stored["key_hint"]

        bearer = {"Authorization": f"Bearer {secret}"}
        anthropic = {"x-api-key": secret}
        gemini = {"x-goog-api-key": secret}
        assert client.get("/v1/models", headers=bearer).status_code == 200
        assert client.post(
            "/v1/messages/count_tokens",
            headers=anthropic,
            json={
                "model": "claude-compatible",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hello"}],
            },
        ).status_code == 200
        assert client.post(
            "/v1beta/models/gemini-compatible:countTokens",
            headers=gemini,
            json={"contents": [{"parts": [{"text": "hello"}]}]},
        ).status_code == 200

        first = client.post(
            "/v1/human/jobs",
            headers=bearer,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "第一个问题"}],
            },
        )
        assert first.status_code == 202
        stored_request = app.state.database.get_request(first.json()["id"])
        assert stored_request is not None
        assert stored_request["api_key_id"] == item["id"]

        queued = client.post(
            "/v1/human/jobs",
            headers=bearer,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "先让我插个队"}],
            },
        )
        assert queued.status_code == 429
        assert queued.headers["retry-after"] == "5"
        assert "先排会儿队" in queued.json()["detail"]

        assert app.state.database.answer_request(
            first.json()["id"],
            {"role": "assistant", "content": "第一个问题答完了。"},
            "msg_managed_key_answer",
        )
        second = client.post(
            "/v1/human/jobs",
            headers=bearer,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "现在轮到我了吗"}],
            },
        )
        assert second.status_code == 202

        paused = client.patch(
            f"/admin/api/api-keys/{item['id']}", json={"active": False}
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert client.get("/v1/models", headers=bearer).status_code == 401

        resumed = client.patch(
            f"/admin/api/api-keys/{item['id']}", json={"active": True}
        )
        assert resumed.status_code == 200
        assert client.get("/v1/models", headers=bearer).status_code == 200

        revoked = client.post(f"/admin/api/api-keys/{item['id']}/revoke")
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert client.get("/v1/models", headers=bearer).status_code == 401
        assert client.get(
            "/v1/models", headers={"Authorization": "Bearer test-api-key"}
        ).status_code == 200


def test_managed_api_key_minute_and_daily_limits(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        login_admin(client)
        minute_secret = client.post(
            "/admin/api/api-keys",
            json={
                "name": "一分钟只问一次",
                "rate_limit_per_minute": 1,
                "daily_limit": 100,
                "max_concurrent": 10,
            },
        ).json()["key"]
        minute_auth = {"Authorization": f"Bearer {minute_secret}"}
        assert client.post(
            "/v1/human/jobs",
            headers=minute_auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "第一次"}],
            },
        ).status_code == 202
        minute_limited = client.post(
            "/v1/chat/completions",
            headers=minute_auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "第二次"}],
            },
        )
        assert minute_limited.status_code == 429
        assert minute_limited.json()["error"]["type"] == "rate_limit_error"
        assert "每分钟最多 1 次" in minute_limited.json()["error"]["message"]
        assert 1 <= int(minute_limited.headers["retry-after"]) <= 60

        daily_secret = client.post(
            "/admin/api/api-keys",
            json={
                "name": "一天只问一次",
                "rate_limit_per_minute": 100,
                "daily_limit": 1,
                "max_concurrent": 10,
            },
        ).json()["key"]
        daily_auth = {"Authorization": f"Bearer {daily_secret}"}
        assert client.post(
            "/v1/human/jobs",
            headers=daily_auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "今天第一次"}],
            },
        ).status_code == 202
        daily_limited = client.post(
            "/v1/human/jobs",
            headers=daily_auth,
            json={
                "model": "test-human",
                "messages": [{"role": "user", "content": "今天第二次"}],
            },
        )
        assert daily_limited.status_code == 429
        assert "每天最多 1 次" in daily_limited.json()["detail"]


def test_official_sdks_accept_managed_key_and_custom_base_url(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        login_admin(client)
        secret = client.post(
            "/admin/api/api-keys",
            json={
                "name": "官方 SDK 契约测试",
                "rate_limit_per_minute": 100,
                "daily_limit": 100,
                "max_concurrent": 10,
            },
        ).json()["key"]

        async def exercise_clients() -> None:
            async def answer_next(source: str, content: str) -> None:
                for _ in range(200):
                    pending = app.state.database.list_requests(status="pending")
                    row = next(
                        (item for item in pending if item["source"] == source), None
                    )
                    if row:
                        assert app.state.database.answer_request(
                            row["id"],
                            {"role": "assistant", "content": content},
                            f"msg_sdk_{source}",
                        )
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError(f"SDK request did not reach queue: {source}")

            openai_http = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app)
            )
            openai_client = AsyncOpenAI(
                api_key=secret,
                base_url="http://iamllm.test/v1",
                http_client=openai_http,
                max_retries=0,
            )
            try:
                models = await openai_client.models.list()
                assert models.data[0].id == "test-human"
                openai_answer = asyncio.create_task(
                    answer_next("openai_responses", "Responses SDK 已接通。")
                )
                response = await openai_client.responses.create(
                    model="gpt-compatible", input="测试官方 Responses SDK"
                )
                await openai_answer
                assert response.output_text == "Responses SDK 已接通。"
            finally:
                await openai_client.close()

            anthropic_http = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app)
            )
            anthropic_client = AsyncAnthropic(
                api_key=secret,
                base_url="http://iamllm.test",
                http_client=anthropic_http,
                max_retries=0,
            )
            try:
                counted = await anthropic_client.messages.count_tokens(
                    model="claude-compatible",
                    messages=[{"role": "user", "content": "hello sdk"}],
                )
                assert counted.input_tokens > 0
                anthropic_answer = asyncio.create_task(
                    answer_next("anthropic_messages", "Claude SDK 已接通。")
                )
                message = await anthropic_client.messages.create(
                    model="claude-compatible",
                    max_tokens=100,
                    messages=[
                        {"role": "user", "content": "测试官方 Claude SDK"}
                    ],
                )
                await anthropic_answer
                assert message.content[0].text == "Claude SDK 已接通。"
            finally:
                await anthropic_client.close()

            gemini_http = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app)
            )
            gemini_client = genai.Client(
                api_key=secret,
                http_options=genai_types.HttpOptions(
                    base_url="http://iamllm.test",
                    api_version="v1beta",
                    httpx_async_client=gemini_http,
                ),
            )
            try:
                gemini_count = await gemini_client.aio.models.count_tokens(
                    model="gemini-compatible", contents="hello sdk"
                )
                assert gemini_count.total_tokens > 0
                gemini_answer = asyncio.create_task(
                    answer_next("gemini_generate_content", "Gemini SDK 已接通。")
                )
                gemini_response = await gemini_client.aio.models.generate_content(
                    model="gemini-compatible", contents="测试官方 Gemini SDK"
                )
                await gemini_answer
                assert gemini_response.text == "Gemini SDK 已接通。"
            finally:
                await gemini_client.aio.aclose()

        asyncio.run(exercise_clients())
