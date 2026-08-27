package domain

import (
	"bytes"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

type RequestStatus string

const (
	StatusPending  RequestStatus = "pending"
	StatusAnswered RequestStatus = "answered"
	StatusExpired  RequestStatus = "expired"
)

var allowedRoles = map[string]bool{
	"developer": true, "system": true, "user": true, "assistant": true, "tool": true,
}

type Message struct {
	ID         string          `json:"id,omitempty"`
	Role       string          `json:"role"`
	Content    json.RawMessage `json:"content,omitempty"`
	Name       string          `json:"name,omitempty"`
	ToolCallID string          `json:"tool_call_id,omitempty"`
	ToolCalls  json.RawMessage `json:"tool_calls,omitempty"`
}

type ToolCall struct {
	ID       string           `json:"id"`
	Type     string           `json:"type"`
	Function ToolCallFunction `json:"function"`
}

type ToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type ResponseMessage struct {
	Role      string          `json:"role"`
	Content   json.RawMessage `json:"content"`
	ToolCalls []ToolCall      `json:"tool_calls,omitempty"`
}

func TextResponse(text string) *ResponseMessage {
	content, _ := json.Marshal(text)
	return &ResponseMessage{Role: "assistant", Content: content}
}

func ToolResponse(name string, arguments map[string]any) (*ResponseMessage, error) {
	if strings.TrimSpace(name) == "" {
		return nil, errors.New("tool name is required")
	}
	encoded, err := json.Marshal(arguments)
	if err != nil {
		return nil, fmt.Errorf("encode tool arguments: %w", err)
	}
	callID, err := NewID("call")
	if err != nil {
		return nil, err
	}
	return &ResponseMessage{
		Role:    "assistant",
		Content: json.RawMessage("null"),
		ToolCalls: []ToolCall{{
			ID: callID, Type: "function",
			Function: ToolCallFunction{Name: name, Arguments: string(encoded)},
		}},
	}, nil
}

func (message *ResponseMessage) Text() string {
	if message == nil {
		return ""
	}
	var value string
	_ = json.Unmarshal(message.Content, &value)
	return value
}

type RequestInput struct {
	Model          string
	Messages       []Message
	Stream         bool
	Tools          []json.RawMessage
	ConversationID string
	Source         string
	Mode           string
	IDPrefix       string
	APIKeyID       string
}

func (input RequestInput) Validate() error {
	if strings.TrimSpace(input.Model) == "" {
		return errors.New("model is required")
	}
	if len(input.Messages) == 0 {
		return errors.New("messages must contain at least one item")
	}
	if len(input.Messages) > 400 {
		return errors.New("messages must contain at most 400 items")
	}
	if len(input.Tools) > 128 {
		return errors.New("tools must contain at most 128 items")
	}
	for index, message := range input.Messages {
		if !allowedRoles[message.Role] {
			return fmt.Errorf("messages[%d].role is invalid", index)
		}
		content := bytes.TrimSpace(message.Content)
		hasContent := len(content) > 0 && !bytes.Equal(content, []byte("null"))
		if !hasContent && len(message.ToolCalls) == 0 {
			return fmt.Errorf("messages[%d] needs content or tool_calls", index)
		}
		if hasContent && content[0] != '"' && content[0] != '[' {
			return fmt.Errorf("messages[%d].content must be a string, an array, or null", index)
		}
		if message.Role == "tool" && strings.TrimSpace(message.ToolCallID) == "" {
			return fmt.Errorf("messages[%d].tool_call_id is required", index)
		}
	}
	return nil
}

type HumanRequest struct {
	ID               string            `json:"id"`
	Model            string            `json:"model"`
	Messages         []Message         `json:"messages,omitempty"`
	Tools            []json.RawMessage `json:"tools,omitempty"`
	Preview          string            `json:"preview"`
	ContextChars     int               `json:"context_chars"`
	MessageCount     int               `json:"message_count"`
	SystemCount      int               `json:"system_count"`
	ToolCount        int               `json:"tool_count"`
	AttachmentCount  int               `json:"attachment_count"`
	Status           RequestStatus     `json:"status"`
	Mode             string            `json:"mode"`
	Source           string            `json:"source"`
	ConversationID   string            `json:"conversation_id,omitempty"`
	StreamRequested  bool              `json:"stream_requested"`
	StreamChunkCount int               `json:"stream_chunk_count"`
	Answer           string            `json:"answer,omitempty"`
	Response         *ResponseMessage  `json:"response,omitempty"`
	AnswerSource     string            `json:"answer_source,omitempty"`
	AutoReplyRuleID  string            `json:"auto_reply_rule_id,omitempty"`
	AutoReplyDueAt   int64             `json:"auto_reply_due_at,omitempty"`
	AutoReplyLabel   string            `json:"auto_reply_label,omitempty"`
	AutoReplyText    string            `json:"-"`
	ClaimOwner       string            `json:"claim_owner,omitempty"`
	ClaimExpiresAt   int64             `json:"claim_expires_at,omitempty"`
	ClientLastSeenAt int64             `json:"client_last_seen_at,omitempty"`
	ReadAt           int64             `json:"read_at,omitempty"`
	Draft            string            `json:"draft,omitempty"`
	DraftUpdatedAt   int64             `json:"draft_updated_at,omitempty"`
	DraftDeviceID    string            `json:"draft_device_id,omitempty"`
	APIKeyID         string            `json:"-"`
	CreatedAt        int64             `json:"created_at"`
	UpdatedAt        int64             `json:"updated_at"`
	AnsweredAt       int64             `json:"answered_at,omitempty"`
	ExpiresAt        int64             `json:"expires_at"`
}

func (request HumanRequest) OwnerAPIKeyID() string { return request.APIKeyID }

type StreamChunk struct {
	RequestID string `json:"request_id"`
	ChunkID   string `json:"chunk_id"`
	Position  int    `json:"position"`
	Content   string `json:"content"`
	CreatedAt int64  `json:"created_at"`
}

func NewHumanRequest(input RequestInput, ttl time.Duration) (HumanRequest, error) {
	if err := input.Validate(); err != nil {
		return HumanRequest{}, err
	}
	prefix := strings.TrimSpace(input.IDPrefix)
	if prefix == "" {
		prefix = "chatcmpl"
	}
	requestID, err := NewID(prefix)
	if err != nil {
		return HumanRequest{}, err
	}
	now := time.Now()
	summary := Summarize(input.Messages, input.Tools)
	mode := input.Mode
	if mode == "" {
		mode = "sync"
	}
	source := input.Source
	if source == "" {
		source = "openai_chat"
	}
	return HumanRequest{
		ID: requestID, Model: strings.TrimSpace(input.Model), Messages: input.Messages,
		Tools: input.Tools, Preview: summary.Preview, ContextChars: summary.ContextChars,
		MessageCount: len(input.Messages), SystemCount: summary.SystemCount,
		ToolCount: summary.ToolCount, AttachmentCount: summary.AttachmentCount,
		Status: StatusPending, Mode: mode, Source: source,
		ConversationID: input.ConversationID, StreamRequested: input.Stream, APIKeyID: input.APIKeyID,
		CreatedAt: now.UnixMilli(), UpdatedAt: now.UnixMilli(), ExpiresAt: now.Add(ttl).Unix(),
	}, nil
}

func NewID(prefix string) (string, error) {
	buffer := make([]byte, 18)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("secure random source unavailable: %w", err)
	}
	return prefix + "_" + base64.RawURLEncoding.EncodeToString(buffer), nil
}

type RequestSummary struct {
	Preview                                               string
	ContextChars, SystemCount, ToolCount, AttachmentCount int
}

var internalBlock = regexp.MustCompile(`(?is)<(system-reminder|environment_context|in-app-browser-context)(?:\s[^>]*)?>.*?</(?:system-reminder|environment_context|in-app-browser-context)>`)
var requestEnvelope = regexp.MustCompile(`(?is)##\s*My request:\s*(.*?)(?:\n\s*<image|\z)`)

func Summarize(messages []Message, tools []json.RawMessage) RequestSummary {
	result := RequestSummary{Preview: "新请求", ToolCount: len(tools)}
	for _, message := range messages {
		result.ContextChars += len([]rune(string(message.Content))) + len([]rune(string(message.ToolCalls)))
		if message.Role == "system" || message.Role == "developer" {
			result.SystemCount++
		}
		if message.Role == "tool" {
			result.ToolCount++
		}
		if len(message.ToolCalls) > 0 {
			var calls []any
			if json.Unmarshal(message.ToolCalls, &calls) == nil {
				result.ToolCount += len(calls)
			}
		}
		result.AttachmentCount += attachmentCount(message.Content)
	}
	for index := len(messages) - 1; index >= 0; index-- {
		if messages[index].Role != "user" {
			continue
		}
		text := CleanUserText(MessageText(messages[index].Content))
		if text != "" {
			result.Preview = shorten(text, 88)
			break
		}
	}
	return result
}

func MessageText(content json.RawMessage) string {
	var text string
	if json.Unmarshal(content, &text) == nil {
		return strings.TrimSpace(text)
	}
	var parts []map[string]any
	if json.Unmarshal(content, &parts) != nil {
		return ""
	}
	values := make([]string, 0, len(parts))
	for _, part := range parts {
		if value, ok := part["text"].(string); ok && strings.TrimSpace(value) != "" {
			values = append(values, strings.TrimSpace(value))
		}
	}
	return strings.Join(values, " ")
}

func CleanUserText(value string) string {
	value = internalBlock.ReplaceAllString(value, "")
	if match := requestEnvelope.FindStringSubmatch(value); len(match) == 2 {
		value = match[1]
	}
	value = strings.TrimSpace(value)
	if strings.HasPrefix(strings.ToLower(value), "sessionstart hook additional context") {
		return ""
	}
	return strings.Join(strings.Fields(value), " ")
}

func attachmentCount(content json.RawMessage) int {
	var parts []map[string]any
	if json.Unmarshal(content, &parts) != nil {
		return 0
	}
	count := 0
	for _, part := range parts {
		typeName, _ := part["type"].(string)
		if strings.Contains(typeName, "image") || strings.Contains(typeName, "file") || typeName == "document" {
			count++
		}
	}
	return count
}

func shorten(value string, limit int) string {
	value = strings.Join(strings.Fields(value), " ")
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit-1]) + "…"
}
