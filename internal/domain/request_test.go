package domain

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestNewHumanRequestExtractsUserPreview(t *testing.T) {
	input := RequestInput{
		Model: "gpt-compatible",
		Messages: []Message{
			{Role: "system", Content: json.RawMessage(`"internal"`)},
			{Role: "user", Content: json.RawMessage(`[{"type":"text","text":"请帮我看看这张图片"},{"type":"image_url","image_url":{"url":"https://example.com/a.png"}}]`)},
		},
		Stream: true,
	}
	request, err := NewHumanRequest(input, time.Hour)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if request.Preview != "请帮我看看这张图片" {
		t.Fatalf("unexpected preview: %q", request.Preview)
	}
	if !strings.HasPrefix(request.ID, "chatcmpl_") {
		t.Fatalf("unexpected request id: %s", request.ID)
	}
	if !request.StreamRequested || request.Status != StatusPending {
		t.Fatalf("unexpected request state: %#v", request)
	}
}

func TestRequestInputRejectsInvalidToolMessage(t *testing.T) {
	input := RequestInput{
		Model:    "human",
		Messages: []Message{{Role: "tool", Content: json.RawMessage(`"result"`)}},
	}
	if err := input.Validate(); err == nil || !strings.Contains(err.Error(), "tool_call_id") {
		t.Fatalf("expected tool_call_id error, got %v", err)
	}
}

func TestRequestInputRejectsNullContentWithoutToolCalls(t *testing.T) {
	input := RequestInput{
		Model:    "human",
		Messages: []Message{{Role: "assistant", Content: json.RawMessage(`null`)}},
	}
	if err := input.Validate(); err == nil || !strings.Contains(err.Error(), "content or tool_calls") {
		t.Fatalf("expected missing content error, got %v", err)
	}
}
