package protocol

import (
	"encoding/json"
	"strings"
	"time"

	"iamllm/internal/domain"
)

func OpenAIResponse(item domain.HumanRequest) map[string]any {
	message := item.Response
	if message == nil {
		message = domain.TextResponse(item.Answer)
	}
	output := []any{}
	if len(message.ToolCalls) > 0 {
		for _, call := range message.ToolCalls {
			output = append(output, map[string]any{"type": "function_call", "id": "fc_" + call.ID, "call_id": call.ID, "name": call.Function.Name, "arguments": call.Function.Arguments, "status": "completed"})
		}
	}
	if text := message.Text(); text != "" {
		output = append(output, map[string]any{"type": "message", "id": "msg_" + strings.TrimPrefix(item.ID, "resp_"), "status": "completed", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": text, "annotations": []any{}}}})
	}
	return map[string]any{"id": item.ID, "object": "response", "created_at": item.CreatedAt / 1000, "status": "completed", "model": item.Model, "output": output, "output_text": message.Text(), "usage": Usage(item), "metadata": map[string]any{"answer_source": item.AnswerSource}}
}

func AnthropicResponse(item domain.HumanRequest) map[string]any {
	message := item.Response
	if message == nil {
		message = domain.TextResponse(item.Answer)
	}
	content := []any{}
	if text := message.Text(); text != "" {
		content = append(content, map[string]any{"type": "text", "text": text})
	}
	for _, call := range message.ToolCalls {
		var arguments map[string]any
		_ = json.Unmarshal([]byte(call.Function.Arguments), &arguments)
		content = append(content, map[string]any{"type": "tool_use", "id": call.ID, "name": call.Function.Name, "input": arguments})
	}
	stop := "end_turn"
	if len(message.ToolCalls) > 0 {
		stop = "tool_use"
	}
	return map[string]any{"id": item.ID, "type": "message", "role": "assistant", "model": item.Model, "content": content, "stop_reason": stop, "stop_sequence": nil, "usage": map[string]any{"input_tokens": RoughTokens(item.Messages), "output_tokens": max(1, len([]rune(message.Text()))/4)}, "human_metadata": map[string]any{"answer_source": item.AnswerSource}}
}

func GeminiResponse(item domain.HumanRequest) map[string]any {
	message := item.Response
	if message == nil {
		message = domain.TextResponse(item.Answer)
	}
	parts := []any{}
	if text := message.Text(); text != "" {
		parts = append(parts, map[string]any{"text": text})
	}
	for _, call := range message.ToolCalls {
		var arguments map[string]any
		_ = json.Unmarshal([]byte(call.Function.Arguments), &arguments)
		parts = append(parts, map[string]any{"functionCall": map[string]any{"id": call.ID, "name": call.Function.Name, "args": arguments}})
	}
	return map[string]any{"candidates": []any{map[string]any{"content": map[string]any{"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}}, "usageMetadata": map[string]any{"promptTokenCount": RoughTokens(item.Messages), "candidatesTokenCount": max(1, len([]rune(message.Text()))/4), "totalTokenCount": RoughTokens(item.Messages) + max(1, len([]rune(message.Text()))/4)}, "modelVersion": item.Model, "responseId": item.ID}
}

func Usage(item domain.HumanRequest) map[string]any {
	input := RoughTokens(item.Messages)
	output := max(1, len([]rune(item.Answer))/4)
	return map[string]any{"input_tokens": input, "output_tokens": output, "total_tokens": input + output}
}
func RoughTokens(messages []domain.Message) int {
	count := 0
	for _, message := range messages {
		count += len([]rune(string(message.Content)))
	}
	if count == 0 {
		return 0
	}
	return max(1, count/4)
}
func CreatedSeconds(item domain.HumanRequest) int64 {
	if item.CreatedAt > 10_000_000_000 {
		return item.CreatedAt / 1000
	}
	if item.CreatedAt == 0 {
		return time.Now().Unix()
	}
	return item.CreatedAt
}
func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
