from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TextContentPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=50_000)


class ImageURLValue(BaseModel):
    url: str = Field(min_length=1, max_length=8_500_000)
    detail: Literal["auto", "low", "high"] | None = None

    @field_validator("url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        allowed = ("https://", "http://", "data:image/", "/uploads/")
        if not value.startswith(allowed):
            raise ValueError("image_url must be http(s), an image data URL, or /uploads")
        return value


class ImageContentPart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageURLValue


ContentPart = TextContentPart | ImageContentPart


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_message(self) -> "ChatMessage":
        if self.content is None and not self.tool_calls:
            raise ValueError("message content is required unless tool_calls are present")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        return self


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=2_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["function"]
    function: FunctionDefinition


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=400)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    user: str | None = None
    tools: list[ToolDefinition] = Field(default_factory=list, max_length=128)
    tool_choice: Any = None
    conversation_id: str | None = None


class PublicChatMessage(BaseModel):
    text: str = Field(default="", max_length=20_000)
    image_urls: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("image_urls")
    @classmethod
    def validate_uploaded_urls(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("/uploads/") for value in values):
            raise ValueError("Only images uploaded to this service are accepted")
        return values

    @model_validator(mode="after")
    def require_content(self) -> "PublicChatMessage":
        if not self.text.strip() and not self.image_urls:
            raise ValueError("A message or image is required")
        return self


class AdminAnswerPayload(BaseModel):
    response_type: Literal["text", "tool_call"] = "text"
    text: str = Field(default="", max_length=50_000)
    tool_name: str = Field(default="", max_length=64)
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    operator_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{12,100}$"
    )


class StreamChunkPayload(BaseModel):
    content: str = Field(max_length=50_000)
    operator_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{12,100}$"
    )

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("流式片段不能为空")
        return value


class AdminOperatorPayload(BaseModel):
    operator_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")


class QuickReplyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=5_000)
    category: str = Field(default="常用", min_length=1, max_length=40)
    active: bool = True


class QuickReplyPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    content: str | None = Field(default=None, min_length=1, max_length=5_000)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    active: bool | None = None


class AutoRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rule_type: Literal["keyword", "schedule"]
    match_type: Literal["contains", "exact"] | None = None
    pattern: str | None = Field(default=None, max_length=200)
    response_text: str = Field(min_length=1, max_length=5_000)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    delay_seconds: int = Field(default=3, ge=0, le=86_400)
    priority: int = Field(default=0, ge=-1000, le=1000)
    active: bool = False

    @field_validator("days")
    @classmethod
    def validate_days(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 6 for value in values):
            raise ValueError("days must contain weekday numbers from 0 to 6")
        return sorted(set(values))

    @model_validator(mode="after")
    def validate_rule_fields(self) -> "AutoRuleCreate":
        if self.rule_type == "keyword" and not (self.pattern or "").strip():
            raise ValueError("keyword rules require a pattern")
        if self.rule_type == "schedule" and not (self.start_time and self.end_time):
            raise ValueError("schedule rules require a start and end time")
        return self


class AutoRulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    rule_type: Literal["keyword", "schedule"] | None = None
    match_type: Literal["contains", "exact"] | None = None
    pattern: str | None = Field(default=None, max_length=200)
    response_text: str | None = Field(default=None, min_length=1, max_length=5_000)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] | None = Field(default=None, min_length=1, max_length=7)
    delay_seconds: int | None = Field(default=None, ge=0, le=86_400)
    priority: int | None = Field(default=None, ge=-1000, le=1000)
    active: bool | None = None

    @field_validator("days")
    @classmethod
    def validate_days(cls, values: list[int] | None) -> list[int] | None:
        if values is not None and any(value < 0 or value > 6 for value in values):
            raise ValueError("days must contain weekday numbers from 0 to 6")
        return sorted(set(values)) if values is not None else None


class AutoRulePreviewPayload(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ProfilePayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str = Field(min_length=1, max_length=2_000)
    availability: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, values: list[str]) -> list[str]:
        return [value.strip()[:100] for value in values if value.strip()]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=1_000)
    daily_limit: int = Field(default=100, ge=1, le=100_000)
    max_concurrent: int = Field(default=3, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be empty")
        return cleaned


class ApiKeyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=1_000)
    daily_limit: int | None = Field(default=None, ge=1, le=100_000)
    max_concurrent: int | None = Field(default=None, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be empty")
        return cleaned
