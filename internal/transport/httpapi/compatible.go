package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"iamllm/internal/application"
	"iamllm/internal/domain"
	"iamllm/internal/protocol"
	"iamllm/internal/repository"
)

func (server *Server) responses(w http.ResponseWriter, r *http.Request) {
	var payload protocol.ResponsesRequest
	if !decodeJSON(w, r, &payload) {
		return
	}
	input, err := protocol.NormalizeResponses(payload)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	input.APIKeyID = apiKeyID(r)
	if payload.PreviousResponseID != "" {
		previous, err := server.service.GetRequest(r.Context(), payload.PreviousResponseID)
		if err != nil {
			server.writeProtocolError(w, r, 404, "not_found_error", "Previous response not found")
			return
		}
		if !requestOwnedBy(r, previous) {
			server.writeProtocolError(w, r, 404, "not_found_error", "Previous response not found")
			return
		}
		if previous.Status != domain.StatusAnswered {
			server.writeProtocolError(w, r, 409, "invalid_request_error", "Previous response has not completed yet")
			return
		}
		history := append([]domain.Message{}, previous.Messages...)
		response := previous.Response
		if response == nil {
			response = domain.TextResponse(previous.Answer)
		}
		encoded, _ := json.Marshal(response.Content)
		history = append(history, domain.Message{Role: "assistant", Content: encoded})
		input.Messages = append(history, input.Messages...)
	}
	item, err := server.service.CreateRequest(r.Context(), input)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	w.Header().Set("X-Human-Request-ID", item.ID)
	if payload.Background {
		writeJSON(w, 200, map[string]any{"id": item.ID, "object": "response", "created_at": item.CreatedAt / 1000, "status": string(item.Status), "model": item.Model, "output": []any{}})
		return
	}
	if payload.Stream {
		_ = server.service.TouchClient(r.Context(), item.ID)
		server.streamResponses(w, r, item)
		return
	}
	answered, err := server.service.WaitForAnswer(r.Context(), item.ID)
	if err != nil {
		server.handleWaitError(w, r, err)
		return
	}
	writeJSON(w, 200, protocol.OpenAIResponse(answered))
}

func (server *Server) responseStatus(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.GetRequest(r.Context(), r.PathValue("id"))
	if errors.Is(err, repository.ErrNotFound) {
		server.writeProtocolError(w, r, 404, "not_found_error", "Response not found")
		return
	}
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	if !requestOwnedBy(r, item) {
		server.writeProtocolError(w, r, 404, "not_found_error", "Response not found")
		return
	}
	if item.Status == domain.StatusAnswered {
		writeJSON(w, 200, protocol.OpenAIResponse(item))
		return
	}
	writeJSON(w, 200, map[string]any{"id": item.ID, "object": "response", "created_at": item.CreatedAt / 1000, "status": string(item.Status), "model": item.Model, "output": []any{}})
}

func (server *Server) streamResponses(w http.ResponseWriter, r *http.Request, item domain.HumanRequest) {
	flusher, ok := startSSE(w)
	if !ok {
		return
	}
	created := map[string]any{"id": item.ID, "object": "response", "created_at": item.CreatedAt / 1000, "status": "in_progress", "model": item.Model, "output": []any{}}
	writeNamedSSE(w, "response.created", map[string]any{"type": "response.created", "response": created})
	writeNamedSSE(w, "response.in_progress", map[string]any{"type": "response.in_progress", "response": created})
	outputIndex := 0
	messageID := "msg_" + strings.TrimPrefix(item.ID, "resp_")
	writeNamedSSE(w, "response.output_item.added", map[string]any{"type": "response.output_item.added", "output_index": outputIndex, "item": map[string]any{"id": messageID, "type": "message", "status": "in_progress", "role": "assistant", "content": []any{}}})
	writeNamedSSE(w, "response.content_part.added", map[string]any{"type": "response.content_part.added", "item_id": messageID, "output_index": outputIndex, "content_index": 0, "part": map[string]any{"type": "output_text", "text": "", "annotations": []any{}}})
	flusher.Flush()
	current, err := server.followTextStream(r, item, func(value string) {
		writeNamedSSE(w, "response.output_text.delta", map[string]any{"type": "response.output_text.delta", "item_id": messageID, "output_index": 0, "content_index": 0, "delta": value})
		flusher.Flush()
	})
	if err != nil {
		return
	}
	if current.Response != nil && len(current.Response.ToolCalls) > 0 {
		for _, call := range current.Response.ToolCalls {
			writeNamedSSE(w, "response.output_item.added", map[string]any{"type": "response.output_item.added", "output_index": outputIndex, "item": map[string]any{"type": "function_call", "id": "fc_" + call.ID, "call_id": call.ID, "name": call.Function.Name, "arguments": "", "status": "in_progress"}})
			writeNamedSSE(w, "response.function_call_arguments.delta", map[string]any{"type": "response.function_call_arguments.delta", "item_id": "fc_" + call.ID, "output_index": outputIndex, "delta": call.Function.Arguments})
			writeNamedSSE(w, "response.function_call_arguments.done", map[string]any{"type": "response.function_call_arguments.done", "item_id": "fc_" + call.ID, "output_index": outputIndex, "arguments": call.Function.Arguments})
			outputIndex++
		}
	}
	text := ""
	if current.Response != nil {
		text = current.Response.Text()
	}
	writeNamedSSE(w, "response.output_text.done", map[string]any{"type": "response.output_text.done", "item_id": messageID, "output_index": 0, "content_index": 0, "text": text})
	writeNamedSSE(w, "response.content_part.done", map[string]any{"type": "response.content_part.done", "item_id": messageID, "output_index": 0, "content_index": 0, "part": map[string]any{"type": "output_text", "text": text, "annotations": []any{}}})
	writeNamedSSE(w, "response.output_item.done", map[string]any{"type": "response.output_item.done", "output_index": 0, "item": map[string]any{"id": messageID, "type": "message", "status": "completed", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": text, "annotations": []any{}}}}})
	writeNamedSSE(w, "response.completed", map[string]any{"type": "response.completed", "response": protocol.OpenAIResponse(current)})
	flusher.Flush()
}

func (server *Server) anthropicMessages(w http.ResponseWriter, r *http.Request) {
	var payload protocol.AnthropicRequest
	if !decodeJSON(w, r, &payload) {
		return
	}
	if payload.MaxTokens <= 0 {
		server.writeProtocolError(w, r, 400, "invalid_request_error", "max_tokens must be greater than zero")
		return
	}
	input, err := protocol.NormalizeAnthropic(payload)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	input.APIKeyID = apiKeyID(r)
	item, err := server.service.CreateRequest(r.Context(), input)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	w.Header().Set("request-id", item.ID)
	if payload.Stream {
		_ = server.service.TouchClient(r.Context(), item.ID)
		server.streamAnthropic(w, r, item)
		return
	}
	answered, err := server.service.WaitForAnswer(r.Context(), item.ID)
	if err != nil {
		server.handleWaitError(w, r, err)
		return
	}
	writeJSON(w, 200, protocol.AnthropicResponse(answered))
}
func (server *Server) anthropicCountTokens(w http.ResponseWriter, r *http.Request) {
	var payload protocol.AnthropicRequest
	if !decodeJSON(w, r, &payload) {
		return
	}
	input, err := protocol.NormalizeAnthropic(payload)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"input_tokens": protocol.RoughTokens(input.Messages)})
}
func (server *Server) streamAnthropic(w http.ResponseWriter, r *http.Request, item domain.HumanRequest) {
	flusher, ok := startSSE(w)
	if !ok {
		return
	}
	writeNamedSSE(w, "message_start", map[string]any{"type": "message_start", "message": map[string]any{"id": item.ID, "type": "message", "role": "assistant", "model": item.Model, "content": []any{}, "stop_reason": nil, "stop_sequence": nil, "usage": map[string]any{"input_tokens": protocol.RoughTokens(item.Messages), "output_tokens": 0}}})
	writeNamedSSE(w, "content_block_start", map[string]any{"type": "content_block_start", "index": 0, "content_block": map[string]any{"type": "text", "text": ""}})
	flusher.Flush()
	current, err := server.followTextStream(r, item, func(value string) {
		writeNamedSSE(w, "content_block_delta", map[string]any{"type": "content_block_delta", "index": 0, "delta": map[string]any{"type": "text_delta", "text": value}})
		flusher.Flush()
	})
	if err != nil {
		return
	}
	writeNamedSSE(w, "content_block_stop", map[string]any{"type": "content_block_stop", "index": 0})
	stop := "end_turn"
	if current.Response != nil && len(current.Response.ToolCalls) > 0 {
		stop = "tool_use"
		for index, call := range current.Response.ToolCalls {
			writeNamedSSE(w, "content_block_start", map[string]any{"type": "content_block_start", "index": index + 1, "content_block": map[string]any{"type": "tool_use", "id": call.ID, "name": call.Function.Name, "input": map[string]any{}}})
			writeNamedSSE(w, "content_block_delta", map[string]any{"type": "content_block_delta", "index": index + 1, "delta": map[string]any{"type": "input_json_delta", "partial_json": call.Function.Arguments}})
			writeNamedSSE(w, "content_block_stop", map[string]any{"type": "content_block_stop", "index": index + 1})
		}
	}
	writeNamedSSE(w, "message_delta", map[string]any{"type": "message_delta", "delta": map[string]any{"stop_reason": stop, "stop_sequence": nil}, "usage": map[string]any{"output_tokens": maxInt(1, len([]rune(current.Answer))/4)}})
	writeNamedSSE(w, "message_stop", map[string]any{"type": "message_stop"})
	flusher.Flush()
}

func (server *Server) geminiGenerate(w http.ResponseWriter, r *http.Request) {
	action := r.PathValue("action")
	model, method, ok := strings.Cut(action, ":")
	if !ok {
		server.writeProtocolError(w, r, 404, "not_found", "Gemini method not found")
		return
	}
	stream := method == "streamGenerateContent"
	if method == "countTokens" {
		stream = false
	}
	if method != "generateContent" && method != "streamGenerateContent" && method != "countTokens" {
		server.writeProtocolError(w, r, 404, "not_found", "Gemini method not found")
		return
	}
	var payload protocol.GeminiRequest
	if !decodeJSON(w, r, &payload) {
		return
	}
	input, err := protocol.NormalizeGemini(model, payload, stream)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_argument", err.Error())
		return
	}
	if method == "countTokens" {
		writeJSON(w, 200, map[string]any{"totalTokens": protocol.RoughTokens(input.Messages)})
		return
	}
	input.APIKeyID = apiKeyID(r)
	item, err := server.service.CreateRequest(r.Context(), input)
	if err != nil {
		server.writeProtocolError(w, r, 400, "invalid_argument", err.Error())
		return
	}
	if stream {
		_ = server.service.TouchClient(r.Context(), item.ID)
		server.streamGemini(w, r, item)
		return
	}
	answered, err := server.service.WaitForAnswer(r.Context(), item.ID)
	if err != nil {
		server.handleWaitError(w, r, err)
		return
	}
	writeJSON(w, 200, protocol.GeminiResponse(answered))
}
func (server *Server) streamGemini(w http.ResponseWriter, r *http.Request, item domain.HumanRequest) {
	flusher, ok := startSSE(w)
	if !ok {
		return
	}
	current, err := server.followTextStream(r, item, func(value string) {
		writeSSE(w, map[string]any{"candidates": []any{map[string]any{"content": map[string]any{"role": "model", "parts": []any{map[string]any{"text": value}}}, "index": 0}}})
		flusher.Flush()
	})
	if err != nil {
		return
	}
	writeSSE(w, protocol.GeminiResponse(current))
	flusher.Flush()
}

func (server *Server) createJob(w http.ResponseWriter, r *http.Request) {
	var payload chatCompletionRequest
	if !decodeJSON(w, r, &payload) {
		return
	}
	input := payload.normalize()
	input.Mode = "async"
	input.IDPrefix = "job"
	input.Source = "human_job"
	input.APIKeyID = apiKeyID(r)
	if err := input.Validate(); err != nil {
		server.writeProtocolError(w, r, 400, "invalid_request_error", err.Error())
		return
	}
	item, err := server.service.CreateRequest(r.Context(), input)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 202, map[string]any{"id": item.ID, "object": "human.job", "status": item.Status, "created_at": item.CreatedAt / 1000, "expires_at": item.ExpiresAt})
}
func (server *Server) getJob(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.GetRequest(r.Context(), r.PathValue("id"))
	if errors.Is(err, repository.ErrNotFound) {
		server.writeProtocolError(w, r, 404, "not_found_error", "Job not found")
		return
	}
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	if !requestOwnedBy(r, item) {
		server.writeProtocolError(w, r, 404, "not_found_error", "Job not found")
		return
	}
	result := map[string]any{"id": item.ID, "object": "human.job", "status": item.Status, "created_at": item.CreatedAt / 1000, "expires_at": item.ExpiresAt}
	if item.Status == domain.StatusAnswered {
		result["response"] = chatCompletion(item)
	}
	writeJSON(w, 200, result)
}

func (server *Server) followTextStream(r *http.Request, item domain.HumanRequest, send func(string)) (domain.HumanRequest, error) {
	position := 0
	lastClientTouch := time.Now()
	timer := time.NewTimer(server.service.ResponseTimeout())
	defer timer.Stop()
	ticker := time.NewTicker(server.service.PollInterval())
	defer ticker.Stop()
	for {
		if time.Since(lastClientTouch) >= 5*time.Second {
			_ = server.service.TouchClient(r.Context(), item.ID)
			lastClientTouch = time.Now()
		}
		current, err := server.service.GetRequest(r.Context(), item.ID)
		if err != nil {
			return current, err
		}
		chunks, err := server.service.ListChunks(r.Context(), item.ID, position)
		if err != nil {
			return current, err
		}
		for _, chunk := range chunks {
			send(chunk.Content)
			position = chunk.Position
		}
		if current.Status == domain.StatusAnswered {
			if position == 0 && current.Answer != "" {
				send(current.Answer)
			}
			return current, nil
		}
		select {
		case <-r.Context().Done():
			return current, r.Context().Err()
		case <-timer.C:
			settled, err := server.service.SettleTimeout(r.Context(), item.ID)
			if err == nil && position == 0 && settled.Answer != "" {
				send(settled.Answer)
			}
			return settled, err
		case <-ticker.C:
		}
	}
}
func (server *Server) handleWaitError(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, context.Canceled) {
		return
	}
	if errors.Is(err, application.ErrResponseTimeout) {
		server.writeProtocolError(w, r, 504, "human_timeout", err.Error())
		return
	}
	server.internalError(w, r, err)
}
func startSSE(w http.ResponseWriter) (http.Flusher, bool) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeJSON(w, 500, map[string]any{"error": "streaming unavailable"})
		return nil, false
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(200)
	return flusher, true
}
func writeNamedSSE(w http.ResponseWriter, event string, value any) {
	payload, _ := json.Marshal(value)
	_, _ = fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, payload)
}
func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

var _ = strconv.Itoa
