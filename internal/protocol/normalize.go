package protocol

import (
	"encoding/json"
	"fmt"
	"strings"

	"iamllm/internal/domain"
)

type ResponsesRequest struct {
	Model              string           `json:"model"`
	Input              any              `json:"input"`
	Instructions       any              `json:"instructions"`
	Stream             bool             `json:"stream"`
	Background         bool             `json:"background"`
	PreviousResponseID string           `json:"previous_response_id"`
	Conversation       any              `json:"conversation"`
	Tools              []map[string]any `json:"tools"`
	Metadata           map[string]any   `json:"metadata"`
}

type AnthropicRequest struct {
	Model     string           `json:"model"`
	Messages  []map[string]any `json:"messages"`
	MaxTokens int              `json:"max_tokens"`
	System    any              `json:"system"`
	Stream    bool             `json:"stream"`
	Tools     []map[string]any `json:"tools"`
	Metadata  map[string]any   `json:"metadata"`
}

type GeminiRequest struct {
	Contents          []map[string]any `json:"contents"`
	SystemInstruction map[string]any   `json:"systemInstruction"`
	Tools             []map[string]any `json:"tools"`
}

func NormalizeResponses(input ResponsesRequest) (domain.RequestInput, error) {
	if input.PreviousResponseID != "" && input.Conversation != nil {
		return domain.RequestInput{}, fmt.Errorf("previous_response_id and conversation cannot be used together")
	}
	messages := []domain.Message{}
	if content := normalContent(input.Instructions); len(content) > 0 {
		messages = append(messages, domain.Message{Role: "system", Content: content})
	}
	switch value := input.Input.(type) {
	case string:
		messages = append(messages, textMessage("user", value))
	case []any:
		for _, raw := range value {
			item, ok := raw.(map[string]any)
			if !ok {
				if text, ok := raw.(string); ok {
					messages = append(messages, textMessage("user", text))
				}
				continue
			}
			typeName, _ := item["type"].(string)
			switch typeName {
			case "message", "":
				role, _ := item["role"].(string)
				if role == "" {
					role = "user"
				}
				content := normalContent(item["content"])
				if len(content) > 0 {
					messages = append(messages, domain.Message{Role: role, Content: content})
				}
			case "function_call":
				callID := stringValue(item["call_id"], stringValue(item["id"], "call_unknown"))
				name := stringValue(item["name"], "unknown")
				arguments := argumentsJSON(item["arguments"])
				calls, _ := json.Marshal([]domain.ToolCall{{ID: callID, Type: "function", Function: domain.ToolCallFunction{Name: name, Arguments: arguments}}})
				messages = append(messages, domain.Message{Role: "assistant", Content: json.RawMessage("null"), ToolCalls: calls})
			case "function_call_output":
				output := textValue(item["output"])
				messages = append(messages, textMessageWithTool("tool", output, stringValue(item["call_id"], stringValue(item["id"], "call_unknown"))))
			}
		}
	default:
		if input.Input != nil {
			return domain.RequestInput{}, fmt.Errorf("input must be a string or an array")
		}
	}
	if len(messages) == 0 {
		return domain.RequestInput{}, fmt.Errorf("input is required")
	}
	conversationID := ""
	if value, ok := input.Conversation.(string); ok {
		conversationID = value
	} else if value, ok := input.Conversation.(map[string]any); ok {
		conversationID = stringValue(value["id"], "")
	}
	return domain.RequestInput{Model: input.Model, Messages: messages, Tools: normalizeResponsesTools(input.Tools), Stream: input.Stream, Source: "openai_responses", Mode: map[bool]string{true: "async", false: "sync"}[input.Background], IDPrefix: "resp", ConversationID: conversationID}, nil
}

func NormalizeAnthropic(input AnthropicRequest) (domain.RequestInput, error) {
	messages := []domain.Message{}
	if content := normalContent(input.System); len(content) > 0 {
		messages = append(messages, domain.Message{Role: "system", Content: content})
	}
	for _, item := range input.Messages {
		role := stringValue(item["role"], "user")
		blocks := asList(item["content"])
		textParts := []any{}
		flush := func() {
			if len(textParts) > 0 {
				encoded, _ := json.Marshal(textParts)
				messages = append(messages, domain.Message{Role: role, Content: encoded})
				textParts = nil
			}
		}
		if text, ok := item["content"].(string); ok {
			messages = append(messages, textMessage(role, text))
			continue
		}
		for _, raw := range blocks {
			block, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			typeName, _ := block["type"].(string)
			switch typeName {
			case "text":
				textParts = append(textParts, map[string]any{"type": "text", "text": stringValue(block["text"], "")})
			case "image":
				if part := anthropicImage(block); part != nil {
					textParts = append(textParts, part)
				}
			case "document":
				textParts = append(textParts, filePart(block))
			case "tool_use":
				flush()
				arguments := argumentsJSON(block["input"])
				calls, _ := json.Marshal([]domain.ToolCall{{ID: stringValue(block["id"], "call_unknown"), Type: "function", Function: domain.ToolCallFunction{Name: stringValue(block["name"], "unknown"), Arguments: arguments}}})
				messages = append(messages, domain.Message{Role: "assistant", Content: json.RawMessage("null"), ToolCalls: calls})
			case "tool_result":
				flush()
				messages = append(messages, textMessageWithTool("tool", textValue(block["content"]), stringValue(block["tool_use_id"], "call_unknown")))
			}
		}
		flush()
	}
	tools := []json.RawMessage{}
	for _, tool := range input.Tools {
		if name, _ := tool["name"].(string); name != "" {
			encoded, _ := json.Marshal(map[string]any{"type": "function", "function": map[string]any{"name": name, "description": tool["description"], "parameters": tool["input_schema"]}})
			tools = append(tools, encoded)
		}
	}
	return domain.RequestInput{Model: input.Model, Messages: messages, Tools: tools, Stream: input.Stream, Source: "anthropic_messages", IDPrefix: "msg"}, nil
}

func NormalizeGemini(model string, input GeminiRequest, stream bool) (domain.RequestInput, error) {
	messages := []domain.Message{}
	if input.SystemInstruction != nil {
		if content := geminiParts(input.SystemInstruction["parts"]); len(content) > 0 {
			messages = append(messages, domain.Message{Role: "system", Content: content})
		}
	}
	for _, item := range input.Contents {
		role := stringValue(item["role"], "user")
		if role == "model" {
			role = "assistant"
		}
		parts := asList(item["parts"])
		normal := []any{}
		for _, raw := range parts {
			part, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			if text, ok := part["text"].(string); ok {
				normal = append(normal, map[string]any{"type": "text", "text": text})
				continue
			}
			if inline, ok := part["inlineData"].(map[string]any); ok {
				mime := stringValue(inline["mimeType"], "application/octet-stream")
				data := stringValue(inline["data"], "")
				if strings.HasPrefix(mime, "image/") {
					normal = append(normal, map[string]any{"type": "image_url", "image_url": map[string]any{"url": "data:" + mime + ";base64," + data}})
				} else {
					normal = append(normal, map[string]any{"type": "file", "file": map[string]any{"mime_type": mime, "url": "data:" + mime + ";base64," + data}})
				}
				continue
			}
			if file, ok := part["fileData"].(map[string]any); ok {
				normal = append(normal, map[string]any{"type": "file", "file": map[string]any{"mime_type": file["mimeType"], "url": file["fileUri"]}})
				continue
			}
			if call, ok := part["functionCall"].(map[string]any); ok {
				if len(normal) > 0 {
					encoded, _ := json.Marshal(normal)
					messages = append(messages, domain.Message{Role: role, Content: encoded})
					normal = nil
				}
				calls, _ := json.Marshal([]domain.ToolCall{{ID: stringValue(call["id"], "call_gemini"), Type: "function", Function: domain.ToolCallFunction{Name: stringValue(call["name"], "unknown"), Arguments: argumentsJSON(call["args"])}}})
				messages = append(messages, domain.Message{Role: "assistant", Content: json.RawMessage("null"), ToolCalls: calls})
				continue
			}
			if response, ok := part["functionResponse"].(map[string]any); ok {
				if len(normal) > 0 {
					encoded, _ := json.Marshal(normal)
					messages = append(messages, domain.Message{Role: role, Content: encoded})
					normal = nil
				}
				messages = append(messages, textMessageWithTool("tool", textValue(response["response"]), stringValue(response["id"], "call_gemini")))
			}
		}
		if len(normal) > 0 {
			encoded, _ := json.Marshal(normal)
			messages = append(messages, domain.Message{Role: role, Content: encoded})
		}
	}
	tools := []json.RawMessage{}
	for _, group := range input.Tools {
		for _, raw := range asList(group["functionDeclarations"]) {
			definition, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			encoded, _ := json.Marshal(map[string]any{"type": "function", "function": map[string]any{"name": definition["name"], "description": definition["description"], "parameters": definition["parameters"]}})
			tools = append(tools, encoded)
		}
	}
	return domain.RequestInput{Model: model, Messages: messages, Tools: tools, Stream: stream, Source: "gemini_generate", IDPrefix: "gemini"}, nil
}

func normalizeResponsesTools(values []map[string]any) []json.RawMessage {
	result := []json.RawMessage{}
	for _, tool := range values {
		if tool["type"] != "function" {
			continue
		}
		name, _ := tool["name"].(string)
		if name == "" {
			if fn, ok := tool["function"].(map[string]any); ok {
				name, _ = fn["name"].(string)
			}
		}
		if name == "" {
			continue
		}
		encoded, _ := json.Marshal(map[string]any{"type": "function", "function": map[string]any{"name": name, "description": tool["description"], "parameters": tool["parameters"]}})
		result = append(result, encoded)
	}
	return result
}
func normalContent(value any) json.RawMessage {
	if value == nil {
		return nil
	}
	if text, ok := value.(string); ok {
		encoded, _ := json.Marshal(text)
		return encoded
	}
	parts := []any{}
	for _, raw := range asList(value) {
		if text, ok := raw.(string); ok {
			parts = append(parts, map[string]any{"type": "text", "text": text})
			continue
		}
		block, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		typeName, _ := block["type"].(string)
		if typeName == "" {
			if text, ok := block["text"].(string); ok {
				parts = append(parts, map[string]any{"type": "text", "text": text})
				continue
			}
		}
		switch typeName {
		case "text", "input_text", "output_text":
			parts = append(parts, map[string]any{"type": "text", "text": stringValue(block["text"], "")})
		case "image", "input_image", "image_url":
			if part := genericImage(block); part != nil {
				parts = append(parts, part)
			}
		case "input_file", "document", "file":
			parts = append(parts, filePart(block))
		case "message":
			nested := normalContent(block["content"])
			var more []any
			if json.Unmarshal(nested, &more) == nil {
				parts = append(parts, more...)
			}
		}
	}
	if len(parts) == 0 {
		return nil
	}
	if len(parts) == 1 {
		if part, ok := parts[0].(map[string]any); ok && part["type"] == "text" {
			encoded, _ := json.Marshal(part["text"])
			return encoded
		}
	}
	encoded, _ := json.Marshal(parts)
	return encoded
}
func geminiParts(value any) json.RawMessage { return normalContent(value) }
func anthropicImage(block map[string]any) map[string]any {
	source, _ := block["source"].(map[string]any)
	if source == nil {
		return nil
	}
	if source["type"] == "base64" {
		return map[string]any{"type": "image_url", "image_url": map[string]any{"url": "data:" + stringValue(source["media_type"], "image/png") + ";base64," + stringValue(source["data"], "")}}
	}
	if source["type"] == "url" {
		return map[string]any{"type": "image_url", "image_url": map[string]any{"url": source["url"]}}
	}
	return nil
}
func genericImage(block map[string]any) map[string]any {
	value := block["image_url"]
	if value == nil {
		value = block["url"]
	}
	if nested, ok := value.(map[string]any); ok {
		value = nested["url"]
	}
	if value == nil {
		value = block["image_url"]
	}
	url, _ := value.(string)
	if url == "" {
		return nil
	}
	return map[string]any{"type": "image_url", "image_url": map[string]any{"url": url}}
}
func filePart(block map[string]any) map[string]any {
	source, _ := block["source"].(map[string]any)
	if source == nil {
		source = map[string]any{}
	}
	value := map[string]any{"filename": first(block["filename"], source["filename"]), "file_id": first(block["file_id"], source["file_id"]), "mime_type": first(block["mime_type"], block["media_type"], source["media_type"]), "url": first(block["file_url"], block["url"], source["url"])}
	return map[string]any{"type": "file", "file": value}
}
func textMessage(role, text string) domain.Message {
	content, _ := json.Marshal(text)
	return domain.Message{Role: role, Content: content}
}
func textMessageWithTool(role, text, id string) domain.Message {
	item := textMessage(role, text)
	item.ToolCallID = id
	return item
}
func asList(value any) []any {
	if list, ok := value.([]any); ok {
		return list
	}
	if value == nil {
		return nil
	}
	return []any{value}
}
func stringValue(value any, fallback string) string {
	if text, ok := value.(string); ok && text != "" {
		return text
	}
	return fallback
}
func textValue(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
func argumentsJSON(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
func first(values ...any) any {
	for _, value := range values {
		if value != nil && value != "" {
			return value
		}
	}
	return nil
}
