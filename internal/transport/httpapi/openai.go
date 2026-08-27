package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"iamllm/internal/application"
	"iamllm/internal/domain"
)

// chatCompletionRequest belongs to the OpenAI adapter. It must be normalized
// before crossing into the application layer.
type chatCompletionRequest struct {
	Model          string            `json:"model"`
	Messages       []domain.Message  `json:"messages"`
	Stream         bool              `json:"stream,omitempty"`
	Tools          []json.RawMessage `json:"tools,omitempty"`
	ConversationID string            `json:"conversation_id,omitempty"`
}

func (input chatCompletionRequest) normalize() domain.RequestInput {
	return domain.RequestInput{
		Model:          input.Model,
		Messages:       input.Messages,
		Stream:         input.Stream,
		Tools:          input.Tools,
		ConversationID: input.ConversationID,
	}
}

func (server *Server) models(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, map[string]any{
		"object": "list",
		"data":   []any{server.modelRecord(server.config.ModelName)},
	})
}

func (server *Server) model(writer http.ResponseWriter, request *http.Request) {
	model := request.PathValue("model")
	if model == "" {
		writeOpenAIError(writer, http.StatusNotFound, "model_not_found", "Model not found")
		return
	}
	writeJSON(writer, http.StatusOK, server.modelRecord(model))
}

func (server *Server) modelRecord(model string) map[string]any {
	profile, _ := server.control.Profile(context.Background())
	return map[string]any{
		"id":       model,
		"object":   "model",
		"created":  0,
		"owned_by": "self-hosted",
		"metadata": map[string]any{
			"display_name": profile.DisplayName,
			"bio":          profile.Bio,
			"skills":       profile.Skills,
			"capabilities": []string{"text", "vision", "streaming", "function_calling", "openai_responses", "anthropic_messages", "gemini_generate_content"},
		},
	}
}

func (server *Server) chatCompletions(writer http.ResponseWriter, request *http.Request) {
	var input chatCompletionRequest
	if !decodeJSON(writer, request, &input) {
		return
	}
	server.serveChatCompletion(writer, request, input, "", apiKeyID(request))
}

// adminPlaygroundChat is the console's private test channel. It deliberately
// takes its model and ownership from server configuration so the browser never
// needs to receive or persist an API key.
func (server *Server) adminPlaygroundChat(writer http.ResponseWriter, request *http.Request) {
	var input chatCompletionRequest
	if !decodeJSON(writer, request, &input) {
		return
	}
	input.Model = server.config.ModelName
	server.serveChatCompletion(writer, request, input, "web_chat", "master")
}

func (server *Server) serveChatCompletion(writer http.ResponseWriter, request *http.Request, input chatCompletionRequest, source, ownerAPIKeyID string) {
	normalized := input.normalize()
	normalized.Source = source
	normalized.APIKeyID = ownerAPIKeyID
	if err := normalized.Validate(); err != nil {
		writeOpenAIError(writer, http.StatusBadRequest, "invalid_request_error", err.Error())
		return
	}
	humanRequest, err := server.service.CreateRequest(request.Context(), normalized)
	if err != nil {
		server.internalError(writer, request, err)
		return
	}
	writer.Header().Set("X-Human-Request-ID", humanRequest.ID)
	if input.Stream {
		_ = server.service.TouchClient(request.Context(), humanRequest.ID)
		server.streamChatCompletion(writer, request, humanRequest)
		return
	}
	answered, err := server.service.WaitForAnswer(request.Context(), humanRequest.ID)
	if errors.Is(err, application.ErrResponseTimeout) {
		writeOpenAIError(writer, http.StatusGatewayTimeout, "human_timeout", err.Error())
		return
	}
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return
		}
		server.internalError(writer, request, err)
		return
	}
	writeJSON(writer, http.StatusOK, chatCompletion(answered))
}

func chatCompletion(request domain.HumanRequest) map[string]any {
	message := request.Response
	if message == nil {
		message = domain.TextResponse(request.Answer)
	}
	finishReason := "stop"
	if len(message.ToolCalls) > 0 {
		finishReason = "tool_calls"
	}
	return map[string]any{
		"id":      request.ID,
		"object":  "chat.completion",
		"created": request.CreatedAt / 1000,
		"model":   request.Model,
		"choices": []any{map[string]any{
			"index":         0,
			"message":       message,
			"finish_reason": finishReason,
		}},
		"human_metadata": map[string]any{"answer_source": request.AnswerSource},
	}
}

func (server *Server) streamChatCompletion(
	writer http.ResponseWriter,
	request *http.Request,
	humanRequest domain.HumanRequest,
) {
	flusher, ok := writer.(http.Flusher)
	if !ok {
		writeOpenAIError(writer, http.StatusInternalServerError, "streaming_unsupported", "Streaming is unavailable")
		return
	}
	writer.Header().Set("Content-Type", "text/event-stream")
	writer.Header().Set("Cache-Control", "no-cache")
	writer.Header().Set("Connection", "keep-alive")
	writer.Header().Set("X-Accel-Buffering", "no")
	writer.WriteHeader(http.StatusOK)
	writeSSE(writer, streamChunk(humanRequest, map[string]any{"role": "assistant"}, nil, ""))
	flusher.Flush()

	position := 0
	lastKeepalive := time.Now()
	lastClientTouch := time.Now()
	timeout := time.NewTimer(server.service.ResponseTimeout())
	defer timeout.Stop()
	ticker := time.NewTicker(server.service.PollInterval())
	defer ticker.Stop()
	for {
		if time.Since(lastClientTouch) >= 5*time.Second {
			_ = server.service.TouchClient(request.Context(), humanRequest.ID)
			lastClientTouch = time.Now()
		}
		current, err := server.service.GetRequest(request.Context(), humanRequest.ID)
		if err != nil {
			server.logger.Error("stream request lookup failed", "request_id", humanRequest.ID, "error", err)
			return
		}
		chunks, err := server.service.ListChunks(request.Context(), humanRequest.ID, position)
		if err != nil {
			server.logger.Error("stream chunk lookup failed", "request_id", humanRequest.ID, "error", err)
			return
		}
		for _, chunk := range chunks {
			writeSSE(writer, streamChunk(current, map[string]any{"content": chunk.Content}, nil, ""))
			position = chunk.Position
			flusher.Flush()
		}
		if current.Status == domain.StatusAnswered {
			if position == 0 && current.Answer != "" {
				writeSSE(writer, streamChunk(current, map[string]any{"content": current.Answer}, nil, ""))
			}
			finish := "stop"
			if current.Response != nil && len(current.Response.ToolCalls) > 0 {
				writeSSE(writer, streamChunk(current, map[string]any{"tool_calls": indexedToolCalls(current.Response.ToolCalls)}, nil, ""))
				finish = "tool_calls"
			}
			writeSSE(writer, streamChunk(current, map[string]any{}, &finish, current.AnswerSource))
			writeSSE(writer, "[DONE]")
			flusher.Flush()
			return
		}
		if time.Since(lastKeepalive) >= 10*time.Second {
			_, _ = fmt.Fprint(writer, ": waiting for human response\n\n")
			flusher.Flush()
			lastKeepalive = time.Now()
		}
		select {
		case <-request.Context().Done():
			return
		case <-timeout.C:
			settled, settleErr := server.service.SettleTimeout(request.Context(), humanRequest.ID)
			if settleErr != nil {
				writeSSE(writer, map[string]any{"error": map[string]any{"type": "human_timeout", "message": settleErr.Error()}})
				writeSSE(writer, "[DONE]")
				flusher.Flush()
				return
			}
			if position == 0 && settled.Answer != "" {
				writeSSE(writer, streamChunk(settled, map[string]any{"content": settled.Answer}, nil, ""))
			}
			finish := "stop"
			writeSSE(writer, streamChunk(settled, map[string]any{}, &finish, settled.AnswerSource))
			writeSSE(writer, "[DONE]")
			flusher.Flush()
			return
		case <-ticker.C:
		}
	}
}

func indexedToolCalls(calls []domain.ToolCall) []any {
	result := make([]any, 0, len(calls))
	for index, call := range calls {
		result = append(result, map[string]any{"index": index, "id": call.ID, "type": call.Type, "function": call.Function})
	}
	return result
}

func streamChunk(
	request domain.HumanRequest,
	delta map[string]any,
	finishReason *string,
	answerSource string,
) map[string]any {
	choice := map[string]any{
		"index":         0,
		"delta":         delta,
		"finish_reason": finishReason,
	}
	event := map[string]any{
		"id":      request.ID,
		"object":  "chat.completion.chunk",
		"created": request.CreatedAt / 1000,
		"model":   request.Model,
		"choices": []any{choice},
	}
	if answerSource != "" {
		event["human_metadata"] = map[string]any{"answer_source": answerSource}
	}
	return event
}

func writeSSE(writer http.ResponseWriter, value any) {
	if value == "[DONE]" {
		_, _ = fmt.Fprint(writer, "data: [DONE]\n\n")
		return
	}
	payload, _ := json.Marshal(value)
	_, _ = fmt.Fprintf(writer, "data: %s\n\n", payload)
}
