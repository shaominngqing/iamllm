from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResponsesCreateRequest(BaseModel):
    """Forgiving subset of OpenAI's Responses create request.

    Unknown fields are intentionally ignored so newer SDKs can talk to the
    human backend without breaking when OpenAI adds optional parameters.
    """

    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[Any] | None = None
    instructions: str | list[Any] | None = None
    stream: bool = False
    background: bool = False
    previous_response_id: str | None = None
    conversation: str | dict[str, Any] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=128)
    tool_choice: Any = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = None
    top_p: float | None = None
    store: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnthropicMessagesRequest(BaseModel):
    """Claude Messages request shape used by the Anthropic SDK/Claude Code."""

    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    max_tokens: int = Field(default=4096, ge=1)
    system: str | list[Any] | None = None
    stream: bool = False
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=128)
    tool_choice: Any = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeminiGenerateRequest(BaseModel):
    """Gemini generateContent request, using the REST API's camelCase keys."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    contents: list[Any] = Field(min_length=1, max_length=400)
    system_instruction: dict[str, Any] | None = Field(
        default=None, alias="systemInstruction"
    )
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=128)
    tool_config: dict[str, Any] | None = Field(default=None, alias="toolConfig")
    generation_config: dict[str, Any] | None = Field(
        default=None, alias="generationConfig"
    )


class GeminiCountTokensRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    contents: list[Any] | None = None
    generate_content_request: dict[str, Any] | None = Field(
        default=None, alias="generateContentRequest"
    )


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:32]
    return f"{prefix}_{digest}"


def response_message_id(response_id: str) -> str:
    return _stable_id("msg", response_id)


def function_item_id(call_id: str) -> str:
    return _stable_id("fc", call_id)


def _text_part(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text:
        return None
    return {"type": "text", "text": text}


def _image_part(block: dict[str, Any]) -> dict[str, Any] | None:
    value: Any = block.get("image_url") or block.get("url")
    detail = block.get("detail")
    if isinstance(value, dict):
        detail = value.get("detail", detail)
        value = value.get("url")

    source = block.get("source")
    if not value and isinstance(source, dict):
        source_type = source.get("type")
        if source_type == "base64" and source.get("data"):
            media_type = source.get("media_type") or "image/png"
            value = f"data:{media_type};base64,{source['data']}"
        elif source_type == "url":
            value = source.get("url")

    if not isinstance(value, str) or not value:
        return None
    image_url: dict[str, Any] = {"url": value}
    if detail in {"auto", "low", "high"}:
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def _file_part(block: dict[str, Any]) -> dict[str, Any]:
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    filename = block.get("filename") or source.get("filename")
    file_id = block.get("file_id") or source.get("file_id")
    mime_type = (
        block.get("mime_type")
        or block.get("media_type")
        or source.get("mime_type")
        or source.get("media_type")
    )
    url = (
        block.get("file_url")
        or block.get("url")
        or source.get("url")
    )
    file_data = block.get("file_data") or source.get("data")
    if not url and isinstance(file_data, str) and file_data:
        url = (
            file_data
            if file_data.startswith("data:")
            else f"data:{mime_type or 'application/octet-stream'};base64,{file_data}"
        )
    return {
        "type": "file",
        "file": {
            "filename": str(filename) if filename else None,
            "file_id": str(file_id) if file_id else None,
            "url": str(url) if url else None,
            "mime_type": str(mime_type) if mime_type else None,
        },
    }


def _normal_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        part = _text_part(content)
        return [part] if part else []
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return []

    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            part = _text_part(block)
            if part:
                parts.append(part)
            continue
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type in {"text", "input_text", "output_text"}:
            part = _text_part(block.get("text"))
            if part:
                parts.append(part)
        elif block_type in {"image", "input_image", "image_url"}:
            part = _image_part(block)
            if part:
                parts.append(part)
            elif block.get("file_id"):
                parts.append(
                    {"type": "text", "text": f"[图片文件：{block['file_id']}]"}
                )
        elif block_type in {"input_file", "document", "file"}:
            parts.append(_file_part(block))
        elif block_type == "message":
            parts.extend(_normal_parts(block.get("content")))
        elif isinstance(block.get("text"), str):
            parts.append({"type": "text", "text": block["text"]})
    return parts


def _message_content(parts: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    if len(parts) == 1 and parts[0]["type"] == "text":
        return str(parts[0]["text"])
    return parts


def _arguments_json(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments or {}, ensure_ascii=False, separators=(",", ":"))


def normalize_responses_messages(payload: ResponsesCreateRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    instruction_parts = _normal_parts(payload.instructions)
    if instruction_parts:
        messages.append(
            {"role": "system", "content": _message_content(instruction_parts)}
        )

    if isinstance(payload.input, str):
        if payload.input:
            messages.append({"role": "user", "content": payload.input})
        return messages

    for item in payload.input or []:
        if isinstance(item, str):
            if item:
                messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "")
        if item_type == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or "call_unknown")
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": str(item.get("name") or "unknown"),
                                "arguments": _arguments_json(item.get("arguments")),
                            },
                        }
                    ],
                }
            )
            continue
        if item_type == "function_call_output":
            output = item.get("output")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False)
            messages.append(
                {
                    "role": "tool",
                    "content": output or "",
                    "tool_call_id": str(item.get("call_id") or item.get("id") or "call_unknown"),
                }
            )
            continue
        if item_type in {"reasoning", "item_reference"}:
            continue

        role = str(item.get("role") or "user")
        if role not in {"developer", "system", "user", "assistant", "tool"}:
            role = "user"
        parts = _normal_parts(item.get("content", item))
        if not parts:
            continue
        message: dict[str, Any] = {
            "role": role,
            "content": _message_content(parts),
        }
        if role == "tool":
            message["tool_call_id"] = str(
                item.get("tool_call_id") or item.get("call_id") or "call_unknown"
            )
        messages.append(message)
    return messages


def normalize_responses_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function" or not tool.get("name"):
            continue
        normalized.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description"),
                    "parameters": tool.get("parameters") or {},
                    "strict": tool.get("strict"),
                },
            }
        )
    return normalized


def _anthropic_result_content(content: Any) -> str | list[dict[str, Any]]:
    parts = _normal_parts(content)
    if parts:
        return _message_content(parts)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


def normalize_anthropic_messages(
    payload: AnthropicMessagesRequest,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_parts = _normal_parts(payload.system)
    if system_parts:
        messages.append({"role": "system", "content": _message_content(system_parts)})

    for source_message in payload.messages:
        role = str(source_message.get("role") or "user")
        content = source_message.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        ordinary_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                call_id = str(block.get("id") or "toolu_unknown")
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or "unknown"),
                            "arguments": _arguments_json(block.get("input")),
                        },
                    }
                )
            elif block_type == "tool_result":
                tool_results.append(
                    {
                        "role": "tool",
                        "content": _anthropic_result_content(block.get("content")),
                        "tool_call_id": str(block.get("tool_use_id") or "toolu_unknown"),
                    }
                )
            elif block_type not in {"thinking", "redacted_thinking"}:
                ordinary_parts.extend(_normal_parts([block]))

        if ordinary_parts or tool_calls:
            message: dict[str, Any] = {
                "role": "assistant" if role == "assistant" else "user",
                "content": _message_content(ordinary_parts) if ordinary_parts else None,
            }
            if tool_calls:
                message["role"] = "assistant"
                message["tool_calls"] = tool_calls
            messages.append(message)
        messages.extend(tool_results)
    return messages


def normalize_anthropic_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not tool.get("name") or not isinstance(tool.get("input_schema"), dict):
            continue
        normalized.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description"),
                    "parameters": tool.get("input_schema") or {},
                },
            }
        )
    return normalized


def _gemini_parts(parts: Any) -> list[dict[str, Any]]:
    if isinstance(parts, str):
        return [{"type": "text", "text": parts}] if parts else []
    if not isinstance(parts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str) and part["text"]:
            normalized.append({"type": "text", "text": part["text"]})
            continue
        inline_data = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline_data, dict):
            mime_type = inline_data.get("mimeType") or inline_data.get("mime_type")
            data = inline_data.get("data")
            if isinstance(mime_type, str) and mime_type.startswith("image/") and data:
                normalized.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{data}"},
                    }
                )
            else:
                normalized.append(
                    _file_part(
                        {
                            "filename": f"inline.{str(mime_type or 'bin').split('/')[-1]}",
                            "mime_type": mime_type,
                            "file_data": data,
                        }
                    )
                )
            continue
        file_data = part.get("fileData") or part.get("file_data")
        if isinstance(file_data, dict):
            mime_type = file_data.get("mimeType") or file_data.get("mime_type")
            uri = file_data.get("fileUri") or file_data.get("file_uri")
            if (
                isinstance(mime_type, str)
                and mime_type.startswith("image/")
                and isinstance(uri, str)
                and uri.startswith(("http://", "https://", "/uploads/"))
            ):
                normalized.append(
                    {"type": "image_url", "image_url": {"url": uri}}
                )
            else:
                normalized.append(
                    _file_part(
                        {
                            "file_url": uri,
                            "mime_type": mime_type,
                        }
                    )
                )
    return normalized


def normalize_gemini_messages(
    payload: GeminiGenerateRequest,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if payload.system_instruction:
        system_parts = _gemini_parts(payload.system_instruction.get("parts"))
        if system_parts:
            messages.append(
                {"role": "system", "content": _message_content(system_parts)}
            )

    for source_content in payload.contents:
        if isinstance(source_content, str):
            if source_content:
                messages.append({"role": "user", "content": source_content})
            continue
        if not isinstance(source_content, dict):
            continue
        role = "assistant" if source_content.get("role") == "model" else "user"
        parts = source_content.get("parts") or []
        ordinary_parts = _gemini_parts(parts)
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict):
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict):
                name = str(function_call.get("name") or "unknown")
                tool_calls.append(
                    {
                        "id": f"call_{name}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": _arguments_json(function_call.get("args")),
                        },
                    }
                )
            function_response = part.get("functionResponse") or part.get(
                "function_response"
            )
            if isinstance(function_response, dict):
                name = str(function_response.get("name") or "unknown")
                response = function_response.get("response")
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": f"call_{name}",
                        "content": (
                            response
                            if isinstance(response, str)
                            else json.dumps(response or {}, ensure_ascii=False)
                        ),
                    }
                )
        if ordinary_parts or tool_calls:
            message: dict[str, Any] = {
                "role": role,
                "content": _message_content(ordinary_parts) if ordinary_parts else None,
            }
            if tool_calls:
                message["role"] = "assistant"
                message["tool_calls"] = tool_calls
            messages.append(message)
        messages.extend(tool_results)
    return messages


def normalize_gemini_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool_group in tools:
        declarations = tool_group.get("functionDeclarations") or tool_group.get(
            "function_declarations"
        )
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if not isinstance(declaration, dict) or not declaration.get("name"):
                continue
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": declaration["name"],
                        "description": declaration.get("description"),
                        "parameters": declaration.get("parameters") or {},
                    },
                }
            )
    return normalized


def _answer_message(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("response") or {
        "role": "assistant",
        "content": row.get("answer") or "",
    }


def _usage(row: dict[str, Any]) -> dict[str, Any]:
    input_tokens = rough_token_count(row.get("messages") or [])
    output_tokens = rough_token_count(_answer_message(row)) if row.get("answer") is not None else 0
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def openai_response_payload(
    row: dict[str, Any],
    *,
    previous_response_id: str | None = None,
    instructions: str | list[Any] | None = None,
    background: bool | None = None,
    metadata: dict[str, Any] | None = None,
    store: bool = True,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    status = (
        "completed"
        if row.get("status") == "answered"
        else "failed"
        if row.get("status") == "expired"
        else "in_progress"
    )
    output: list[dict[str, Any]] = []
    if status == "completed":
        message = _answer_message(row)
        content = message.get("content")
        if content is not None:
            output.append(
                {
                    "id": response_message_id(row["id"]),
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": str(content),
                            "annotations": [],
                            "logprobs": [],
                        }
                    ],
                }
            )
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            call_id = str(call.get("id") or "call_unknown")
            output.append(
                {
                    "id": function_item_id(call_id),
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": str(function.get("name") or "unknown"),
                    "arguments": _arguments_json(function.get("arguments")),
                }
            )

    background = row.get("mode") == "async" if background is None else background
    result: dict[str, Any] = {
        "id": row["id"],
        "object": "response",
        "created_at": row["created_at"],
        "status": status,
        "background": background,
        "completed_at": row.get("answered_at") if status == "completed" else None,
        "error": (
            {"code": "human_timeout", "message": "The human response expired"}
            if status == "failed"
            else None
        ),
        "incomplete_details": None,
        "instructions": instructions,
        "max_output_tokens": max_output_tokens,
        "max_tool_calls": None,
        "model": row["model"],
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": previous_response_id,
        "prompt_cache_key": None,
        "reasoning": {"effort": None, "summary": None},
        "safety_identifier": None,
        "service_tier": "default",
        "store": store,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": 0,
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": _usage(row) if status == "completed" else None,
        "user": None,
        "metadata": metadata or {},
    }
    if row.get("answer_source"):
        result["human_metadata"] = {"answer_source": row["answer_source"]}
    return result


def _parsed_tool_input(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(arguments or "")}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def anthropic_message_payload(row: dict[str, Any]) -> dict[str, Any]:
    message = _answer_message(row)
    content: list[dict[str, Any]] = []
    if message.get("content") is not None:
        content.append({"type": "text", "text": str(message["content"])})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or "toolu_unknown"),
                "name": str(function.get("name") or "unknown"),
                "input": _parsed_tool_input(function.get("arguments")),
            }
        )
    input_tokens = rough_token_count(row.get("messages") or [])
    output_tokens = rough_token_count(content)
    result: dict[str, Any] = {
        "id": row["id"],
        "type": "message",
        "role": "assistant",
        "model": row["model"],
        "content": content,
        "stop_reason": "tool_use" if message.get("tool_calls") else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": output_tokens,
        },
    }
    if row.get("answer_source"):
        result["human_metadata"] = {"answer_source": row["answer_source"]}
    return result


def gemini_response_payload(row: dict[str, Any]) -> dict[str, Any]:
    message = _answer_message(row)
    parts: list[dict[str, Any]] = []
    if message.get("content") is not None:
        parts.append({"text": str(message["content"])})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        parts.append(
            {
                "functionCall": {
                    "name": str(function.get("name") or "unknown"),
                    "args": _parsed_tool_input(function.get("arguments")),
                }
            }
        )
    prompt_tokens = rough_token_count(row.get("messages") or [])
    output_tokens = rough_token_count(parts)
    result: dict[str, Any] = {
        "candidates": [
            {
                "content": {"parts": parts, "role": "model"},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
            "totalTokenCount": prompt_tokens + output_tokens,
        },
        "modelVersion": row["model"],
        "responseId": row["id"],
    }
    if row.get("answer_source"):
        result["humanMetadata"] = {"answerSource": row["answer_source"]}
    return result


def rough_token_count(value: Any) -> int:
    """Small deterministic estimate for compatibility-only usage fields."""

    pieces: list[str] = []

    def collect(current: Any) -> None:
        if isinstance(current, str):
            pieces.append(current)
        elif isinstance(current, dict):
            for item in current.values():
                collect(item)
        elif isinstance(current, list):
            for item in current:
                collect(item)

    collect(value)
    characters = sum(len(piece) for piece in pieces)
    return max(1, (characters + 3) // 4) if characters else 0
