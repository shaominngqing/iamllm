from __future__ import annotations

import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
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
        assert finished.json()["answer"] == "普通第一段，普通第二段。"
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
        assert client.get("/chat").status_code == 200
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
        assert finished.json()["answer"] == "第一段，第二段。"
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


def test_unified_admin_and_automation_crud(tmp_path: Path) -> None:
    app = create_app(build_settings(tmp_path))

    with TestClient(app) as client:
        login_admin(client)
        page = client.get("/admin")
        assert page.status_code == 200
        assert "人类模型控制台" in page.text
        assert "快捷话术" in page.text
        assert "自动回复规则" in page.text
        assert "空闲自动接单" in page.text

        chat_page = client.get("/chat")
        assert "超时会自动说明情况" in chat_page.text
        assert "不冒充真人" in chat_page.text

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
        assert finished.json()["answer"] == "由 A 回答第一段。"
        assert finished.json()["claim_active"] is False


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
