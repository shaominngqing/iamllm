from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any, AsyncIterator

from app.config import Settings
from app.protocols import (
    ResponsesCreateRequest,
    anthropic_message_payload,
    function_item_id,
    gemini_response_payload,
    openai_response_payload,
    response_message_id,
    rough_token_count,
)
from app.repositories import HumanRequestRepository


def chat_completion(row: dict[str, Any]) -> dict[str, Any]:
    message = row["response"] or {"role": "assistant", "content": row["answer"]}
    finish_reason = "tool_calls" if message.get("tool_calls") else "stop"
    result = {
        "id": row["id"],
        "object": "chat.completion",
        "created": row["created_at"],
        "model": row["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
    }
    if row.get("conversation_id"):
        result["conversation_id"] = row["conversation_id"]
    if row.get("answer_source"):
        result["human_metadata"] = {"answer_source": row["answer_source"]}
    return result


def _stream_event(data: dict[str, Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _stream_base(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": current["id"],
        "object": "chat.completion.chunk",
        "created": current["created_at"],
        "model": current["model"],
    }


def _stream_role_event(current: dict[str, Any]) -> str:
    return _stream_event(
        {
            **_stream_base(current),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
            "human_metadata": {"answer_source": "human_stream"},
        }
    )


def _stream_content_event(current: dict[str, Any], content: str) -> str:
    return _stream_event(
        {
            **_stream_base(current),
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
    )


def _stream_finish_events(
    current: dict[str, Any], *, finish_reason: str = "stop"
) -> list[str]:
    return [
        _stream_event(
            {
                **_stream_base(current),
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason}
                ],
                "human_metadata": {
                    "answer_source": current.get("answer_source") or "human"
                },
            }
        ),
        _stream_event("[DONE]"),
    ]


def _stream_answer_events(
    current: dict[str, Any], *, include_role: bool = True
) -> list[str]:
    message = current["response"] or {
        "role": "assistant",
        "content": current["answer"],
    }
    events: list[str] = []
    if include_role:
        events.append(_stream_role_event(current))
    if message.get("content") is not None:
        events.append(_stream_content_event(current, message["content"]))
    if message.get("tool_calls"):
        events.append(
            _stream_event(
                {
                    **_stream_base(current),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": index, **tool_call}
                                    for index, tool_call in enumerate(
                                        message["tool_calls"]
                                    )
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
    events.extend(
        _stream_finish_events(
            current,
            finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        )
    )
    return events


def pick_timeout_fallback(settings: Settings) -> str:
    options = [
        option.strip()
        for option in settings.timeout_fallback_text.split("||")
        if option.strip()
    ]
    return secrets.choice(options) if options else ""


def _settle_sync_timeout(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> dict[str, Any] | None:
    current = database.get_request(row["id"])
    if current and current["status"] == "answered":
        return current
    if current and current["stream_chunk_count"]:
        database.finalize_stream_request(
            row["id"],
            f"msg_timeout_partial_{row['id']}",
            answer_source="human_timeout_partial",
        )
        partial = database.get_request(row["id"])
        if partial and partial["status"] == "answered":
            return partial
    timeout_fallback = pick_timeout_fallback(settings)
    if timeout_fallback:
        database.answer_request(
            row["id"],
            {"role": "assistant", "content": timeout_fallback},
            f"msg_timeout_{row['id']}",
            answer_source="timeout_fallback",
        )
        current = database.get_request(row["id"])
        if current and current["status"] == "answered":
            return current
    database.expire_request(row["id"])
    return None


async def wait_for_human_answer(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> dict[str, Any] | None:
    while True:
        current = database.get_request(row["id"])
        if current and current["status"] == "answered":
            return current
        if (
            not current
            or current["status"] == "expired"
            or current["expires_at"] <= int(time.time())
        ):
            break
        database.touch_client_connection(row["id"])
        await asyncio.sleep(settings.poll_interval_seconds)
    return _settle_sync_timeout(database, row, settings)


async def completion_stream(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> AsyncIterator[str]:
    last_position = 0
    last_keepalive = time.monotonic()
    live_stream = bool(row.get("stream_requested"))
    if live_stream:
        yield _stream_role_event(row)
    while True:
        if live_stream:
            database.touch_client_connection(row["id"])
        current = database.get_request(row["id"])
        if live_stream:
            chunks = database.list_stream_chunks(
                row["id"], after_position=last_position
            )
            for chunk in chunks:
                yield _stream_content_event(current or row, chunk["content"])
                last_position = chunk["position"]
        if current and current["status"] == "answered":
            if live_stream and last_position:
                events = _stream_finish_events(current)
            else:
                events = _stream_answer_events(
                    current, include_role=not live_stream
                )
            for event in events:
                yield event
            return
        if (
            not current
            or current["status"] == "expired"
            or current["expires_at"] <= int(time.time())
        ):
            break
        if time.monotonic() - last_keepalive >= settings.stream_keepalive_seconds:
            yield ": 真人模型还在输入框附近\n\n"
            last_keepalive = time.monotonic()
        await asyncio.sleep(settings.poll_interval_seconds)

    if live_stream:
        final_chunks = database.list_stream_chunks(
            row["id"], after_position=last_position
        )
        for chunk in final_chunks:
            yield _stream_content_event(row, chunk["content"])
            last_position = chunk["position"]
        timed_current = database.get_request(row["id"])
        if timed_current and timed_current["status"] == "answered":
            events = (
                _stream_finish_events(timed_current)
                if last_position
                else _stream_answer_events(timed_current, include_role=False)
            )
            for event in events:
                yield event
            return
    if live_stream and last_position:
        database.finalize_stream_request(
            row["id"],
            f"msg_timeout_partial_{row['id']}",
            answer_source="human_timeout_partial",
        )
        partial = database.get_request(row["id"])
        if partial and partial["status"] == "answered":
            for event in _stream_finish_events(partial):
                yield event
            return
    fallback = _settle_sync_timeout(database, row, settings)
    if fallback:
        for event in _stream_answer_events(
            fallback, include_role=not live_stream
        ):
            yield event
        return
    yield _stream_event(
        {
            "error": {
                "message": "The human did not answer before the request timed out",
                "type": "human_timeout",
                "request_id": row["id"],
            }
        }
    )
    yield _stream_event("[DONE]")


def _named_stream_event(event_type: str, data: dict[str, Any]) -> str:
    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _human_protocol_events(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> AsyncIterator[dict[str, Any]]:
    """Expose one human answer as protocol-neutral lifecycle events."""

    last_position = 0
    last_keepalive = time.monotonic()
    yield {"type": "start", "row": row}

    while True:
        database.touch_client_connection(row["id"])
        current = database.get_request(row["id"])
        chunks = database.list_stream_chunks(
            row["id"], after_position=last_position
        )
        for chunk in chunks:
            yield {
                "type": "text",
                "row": current or row,
                "content": chunk["content"],
            }
            last_position = chunk["position"]

        if current and current["status"] == "answered":
            if not last_position:
                message = current["response"] or {
                    "role": "assistant",
                    "content": current["answer"],
                }
                if message.get("content") is not None:
                    yield {
                        "type": "text",
                        "row": current,
                        "content": str(message["content"]),
                    }
                if message.get("tool_calls"):
                    yield {
                        "type": "tool_calls",
                        "row": current,
                        "tool_calls": message["tool_calls"],
                    }
            yield {"type": "finish", "row": current}
            return

        if (
            not current
            or current["status"] == "expired"
            or current["expires_at"] <= int(time.time())
        ):
            break
        if time.monotonic() - last_keepalive >= settings.stream_keepalive_seconds:
            yield {"type": "keepalive", "row": current}
            last_keepalive = time.monotonic()
        await asyncio.sleep(settings.poll_interval_seconds)

    final_chunks = database.list_stream_chunks(
        row["id"], after_position=last_position
    )
    for chunk in final_chunks:
        yield {"type": "text", "row": row, "content": chunk["content"]}
        last_position = chunk["position"]

    timed_current = database.get_request(row["id"])
    if timed_current and timed_current["status"] == "answered":
        yield {"type": "finish", "row": timed_current}
        return
    if last_position:
        database.finalize_stream_request(
            row["id"],
            f"msg_timeout_partial_{row['id']}",
            answer_source="human_timeout_partial",
        )
        partial = database.get_request(row["id"])
        if partial and partial["status"] == "answered":
            yield {"type": "finish", "row": partial}
            return

    fallback = _settle_sync_timeout(database, row, settings)
    if fallback:
        message = fallback["response"] or {
            "role": "assistant",
            "content": fallback["answer"],
        }
        if message.get("content") is not None:
            yield {
                "type": "text",
                "row": fallback,
                "content": str(message["content"]),
            }
        if message.get("tool_calls"):
            yield {
                "type": "tool_calls",
                "row": fallback,
                "tool_calls": message["tool_calls"],
            }
        yield {"type": "finish", "row": fallback}
        return

    yield {
        "type": "error",
        "row": row,
        "message": "The human did not answer before the request timed out",
    }


async def responses_stream(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
    payload: ResponsesCreateRequest,
) -> AsyncIterator[str]:
    sequence_number = 0
    text_open = False
    text_value = ""
    output_index = 0
    message_id = response_message_id(row["id"])

    def event(event_type: str, **values: Any) -> str:
        nonlocal sequence_number
        data = {
            "type": event_type,
            **values,
            "sequence_number": sequence_number,
        }
        sequence_number += 1
        return _named_stream_event(event_type, data)

    async for human_event in _human_protocol_events(database, row, settings):
        event_type = human_event["type"]
        current = human_event["row"]
        if event_type == "start":
            response = openai_response_payload(
                current,
                previous_response_id=payload.previous_response_id,
                instructions=payload.instructions,
                metadata=payload.metadata,
                store=payload.store,
                max_output_tokens=payload.max_output_tokens,
            )
            yield event("response.created", response=response)
            yield event("response.in_progress", response=response)
        elif event_type == "keepalive":
            yield ": 真人模型还在输入框附近\n\n"
        elif event_type == "text":
            if not text_open:
                text_open = True
                yield event(
                    "response.output_item.added",
                    output_index=output_index,
                    item={
                        "id": message_id,
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                )
                yield event(
                    "response.content_part.added",
                    item_id=message_id,
                    output_index=output_index,
                    content_index=0,
                    part={"type": "output_text", "text": "", "annotations": []},
                )
            delta = human_event["content"]
            text_value += delta
            yield event(
                "response.output_text.delta",
                item_id=message_id,
                output_index=output_index,
                content_index=0,
                delta=delta,
                logprobs=[],
            )
        elif event_type == "tool_calls":
            if text_open:
                yield event(
                    "response.output_text.done",
                    item_id=message_id,
                    output_index=output_index,
                    content_index=0,
                    text=text_value,
                    logprobs=[],
                )
                part = {
                    "type": "output_text",
                    "text": text_value,
                    "annotations": [],
                }
                yield event(
                    "response.content_part.done",
                    item_id=message_id,
                    output_index=output_index,
                    content_index=0,
                    part=part,
                )
                yield event(
                    "response.output_item.done",
                    output_index=output_index,
                    item={
                        "id": message_id,
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [part],
                    },
                )
                text_open = False
                output_index += 1
            for tool_call in human_event["tool_calls"]:
                function = tool_call.get("function") or {}
                call_id = str(tool_call.get("id") or "call_unknown")
                item_id = function_item_id(call_id)
                arguments = str(function.get("arguments") or "{}")
                item = {
                    "id": item_id,
                    "type": "function_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": str(function.get("name") or "unknown"),
                    "arguments": "",
                }
                yield event(
                    "response.output_item.added",
                    output_index=output_index,
                    item=item,
                )
                yield event(
                    "response.function_call_arguments.delta",
                    item_id=item_id,
                    output_index=output_index,
                    delta=arguments,
                )
                yield event(
                    "response.function_call_arguments.done",
                    item_id=item_id,
                    output_index=output_index,
                    arguments=arguments,
                )
                yield event(
                    "response.output_item.done",
                    output_index=output_index,
                    item={**item, "status": "completed", "arguments": arguments},
                )
                output_index += 1
        elif event_type == "finish":
            if text_open:
                yield event(
                    "response.output_text.done",
                    item_id=message_id,
                    output_index=output_index,
                    content_index=0,
                    text=text_value,
                    logprobs=[],
                )
                part = {
                    "type": "output_text",
                    "text": text_value,
                    "annotations": [],
                }
                yield event(
                    "response.content_part.done",
                    item_id=message_id,
                    output_index=output_index,
                    content_index=0,
                    part=part,
                )
                yield event(
                    "response.output_item.done",
                    output_index=output_index,
                    item={
                        "id": message_id,
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [part],
                    },
                )
                text_open = False
            response = openai_response_payload(
                current,
                previous_response_id=payload.previous_response_id,
                instructions=payload.instructions,
                metadata=payload.metadata,
                store=payload.store,
                max_output_tokens=payload.max_output_tokens,
            )
            yield event("response.completed", response=response)
            return
        elif event_type == "error":
            yield event(
                "error",
                code="human_timeout",
                message=human_event["message"],
                param=None,
            )
            return


async def anthropic_stream(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> AsyncIterator[str]:
    text_open = False
    text_value = ""
    block_index = 0

    def event(event_type: str, data: dict[str, Any]) -> str:
        return _named_stream_event(event_type, data)

    async for human_event in _human_protocol_events(database, row, settings):
        event_type = human_event["type"]
        current = human_event["row"]
        if event_type == "start":
            yield event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": row["id"],
                        "type": "message",
                        "role": "assistant",
                        "model": row["model"],
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {
                            "input_tokens": rough_token_count(row.get("messages") or []),
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 0,
                        },
                    },
                },
            )
        elif event_type == "keepalive":
            yield event("ping", {"type": "ping"})
        elif event_type == "text":
            if not text_open:
                text_open = True
                yield event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            delta = human_event["content"]
            text_value += delta
            yield event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {"type": "text_delta", "text": delta},
                },
            )
        elif event_type == "tool_calls":
            if text_open:
                yield event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": block_index},
                )
                text_open = False
                block_index += 1
            for tool_call in human_event["tool_calls"]:
                function = tool_call.get("function") or {}
                arguments = str(function.get("arguments") or "{}")
                yield event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": str(tool_call.get("id") or "toolu_unknown"),
                            "name": str(function.get("name") or "unknown"),
                            "input": {},
                        },
                    },
                )
                yield event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": arguments,
                        },
                    },
                )
                yield event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": block_index},
                )
                block_index += 1
        elif event_type == "finish":
            if text_open:
                yield event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": block_index},
                )
                text_open = False
            final_message = anthropic_message_payload(current)
            yield event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": final_message["stop_reason"],
                        "stop_sequence": None,
                    },
                    "usage": {
                        "output_tokens": final_message["usage"]["output_tokens"]
                    },
                },
            )
            yield event("message_stop", {"type": "message_stop"})
            return
        elif event_type == "error":
            yield event(
                "error",
                {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": human_event["message"],
                    },
                },
            )
            return


async def gemini_stream(
    database: HumanRequestRepository,
    row: dict[str, Any],
    settings: Settings,
) -> AsyncIterator[str]:
    async for human_event in _human_protocol_events(database, row, settings):
        event_type = human_event["type"]
        current = human_event["row"]
        if event_type == "keepalive":
            yield ": 真人模型还在输入框附近\n\n"
        elif event_type == "text":
            yield _stream_event(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": human_event["content"]}],
                                "role": "model",
                            },
                            "index": 0,
                        }
                    ],
                    "modelVersion": row["model"],
                    "responseId": row["id"],
                }
            )
        elif event_type == "tool_calls":
            payload = gemini_response_payload(current)
            parts = [
                part
                for part in payload["candidates"][0]["content"]["parts"]
                if "functionCall" in part
            ]
            if parts:
                yield _stream_event(
                    {
                        "candidates": [
                            {
                                "content": {"parts": parts, "role": "model"},
                                "index": 0,
                            }
                        ],
                        "modelVersion": row["model"],
                        "responseId": row["id"],
                    }
                )
        elif event_type == "finish":
            payload = gemini_response_payload(current)
            yield _stream_event(
                {
                    "candidates": [
                        {
                            "content": {"parts": [], "role": "model"},
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": payload["usageMetadata"],
                    "modelVersion": row["model"],
                    "responseId": row["id"],
                }
            )
            return
        elif event_type == "error":
            yield _stream_event(
                {
                    "error": {
                        "code": 504,
                        "message": human_event["message"],
                        "status": "DEADLINE_EXCEEDED",
                    }
                }
            )
            return
