package httpapi

import (
	"compress/gzip"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

func (server *Server) adminOverview(w http.ResponseWriter, r *http.Request) {
	pending, err := server.service.PendingCount(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	keys, _ := server.control.ListAPIKeys(r.Context())
	devices, _ := server.control.Devices(r.Context())
	writeJSON(w, 200, map[string]any{"pending": pending, "managed_keys": len(keys), "devices": len(devices), "model": server.config.ModelName, "runtime": "go", "database": "sqlite", "environment": server.config.Environment, "public_base_url": publicBase(server.config.PublicBaseURL, r), "stream_chunk_delay_ms": server.config.StreamChunkDelay.Milliseconds(), "stream_chunk_chars": server.config.StreamChunkChars, "response_timeout_seconds": int(server.config.ResponseTimeout.Seconds())})
}

func (server *Server) adminEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := startSSE(w)
	if !ok {
		return
	}
	after, _ := strconv.ParseInt(r.Header.Get("Last-Event-ID"), 10, 64)
	if query, _ := strconv.ParseInt(r.URL.Query().Get("after"), 10, 64); query > after {
		after = query
	}
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	heartbeat := time.NewTicker(15 * time.Second)
	defer heartbeat.Stop()
	for {
		items, err := server.service.ListEvents(r.Context(), after, 200)
		if err != nil {
			return
		}
		for _, item := range items {
			payload, _ := json.Marshal(item)
			_, _ = fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", item.ID, item.Type, payload)
			after = item.ID
		}
		if len(items) > 0 {
			flusher.Flush()
		}
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
		case <-heartbeat.C:
			_, _ = fmt.Fprint(w, ": heartbeat\n\n")
			flusher.Flush()
		}
	}
}

func (server *Server) adminRequests(w http.ResponseWriter, r *http.Request) {
	status := domain.RequestStatus(r.URL.Query().Get("status"))
	if status == "" {
		status = domain.RequestStatus(r.URL.Query().Get("filter"))
	}
	if status != "" && status != domain.StatusPending && status != domain.StatusAnswered && status != domain.StatusExpired {
		writeAdminError(w, 400, "invalid_status", "status must be pending, answered, or expired")
		return
	}
	limit := 100
	if raw := r.URL.Query().Get("limit"); raw != "" {
		value, err := strconv.Atoi(raw)
		if err != nil || value < 1 || value > 500 {
			writeAdminError(w, 400, "invalid_limit", "limit must be between 1 and 500")
			return
		}
		limit = value
	}
	beforeCreatedAt, beforeID, err := decodeRequestCursor(r.URL.Query().Get("cursor"))
	if err != nil {
		writeAdminError(w, 400, "invalid_cursor", "cursor is invalid")
		return
	}
	items, err := server.service.ListRequests(r.Context(), status, limit+1, beforeCreatedAt, beforeID)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	hasMore := len(items) > limit
	if hasMore {
		items = items[:limit]
	}
	result := []any{}
	for _, item := range items {
		result = append(result, adminRequest(item, nil, false))
	}
	nextCursor := ""
	if hasMore && len(items) > 0 {
		last := items[len(items)-1]
		nextCursor = encodeRequestCursor(last.CreatedAt, last.ID)
	}
	writeJSON(w, 200, map[string]any{"items": result, "total": len(result), "has_more": hasMore, "next_cursor": nextCursor})
}

func encodeRequestCursor(createdAt int64, id string) string {
	return base64.RawURLEncoding.EncodeToString([]byte(strconv.FormatInt(createdAt, 10) + "|" + id))
}

func decodeRequestCursor(value string) (int64, string, error) {
	if value == "" {
		return 0, "", nil
	}
	decoded, err := base64.RawURLEncoding.DecodeString(value)
	if err != nil {
		return 0, "", err
	}
	timestamp, id, ok := strings.Cut(string(decoded), "|")
	if !ok || id == "" {
		return 0, "", errors.New("malformed cursor")
	}
	createdAt, err := strconv.ParseInt(timestamp, 10, 64)
	return createdAt, id, err
}
func (server *Server) adminRequest(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.GetRequest(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	chunks, err := server.service.ListChunks(r.Context(), item.ID, 0)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, chunks, true))
}
func (server *Server) adminRawRequest(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.GetRequest(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	payload := map[string]any{"id": item.ID, "messages": item.Messages, "tools": item.Tools, "response": item.Response}
	if strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
		w.Header().Set("Content-Encoding", "gzip")
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		writer := gzip.NewWriter(w)
		defer writer.Close()
		_ = json.NewEncoder(writer).Encode(payload)
		return
	}
	writeJSON(w, 200, payload)
}
func (server *Server) adminAttachment(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.GetRequest(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	messageIndex, err1 := strconv.Atoi(r.PathValue("message"))
	partIndex, err2 := strconv.Atoi(r.PathValue("part"))
	if err1 != nil || err2 != nil || messageIndex < 0 || messageIndex >= len(item.Messages) {
		http.NotFound(w, r)
		return
	}
	var parts []map[string]any
	if json.Unmarshal(item.Messages[messageIndex].Content, &parts) != nil || partIndex < 0 || partIndex >= len(parts) {
		http.NotFound(w, r)
		return
	}
	value := attachmentValue(parts[partIndex])
	if !strings.HasPrefix(value, "data:") || !strings.Contains(value, ",") {
		http.NotFound(w, r)
		return
	}
	metadata, encoded, _ := strings.Cut(strings.TrimPrefix(value, "data:"), ",")
	mediaType := strings.Split(metadata, ";")[0]
	if mediaType == "" {
		mediaType = "application/octet-stream"
	}
	var content []byte
	if strings.Contains(strings.ToLower(metadata), ";base64") {
		content, err = base64.StdEncoding.DecodeString(encoded)
	} else {
		var decoded string
		decoded, err = url.PathUnescape(encoded)
		content = []byte(decoded)
	}
	if err != nil {
		writeAdminError(w, 422, "invalid_attachment", "Attachment data is invalid")
		return
	}
	w.Header().Set("Content-Type", mediaType)
	w.Header().Set("Cache-Control", "private,max-age=3600")
	w.Header().Set("Content-Disposition", "inline")
	_, _ = w.Write(content)
}
func (server *Server) adminAppendChunk(w http.ResponseWriter, r *http.Request) {
	var p struct {
		ChunkID    string `json:"chunk_id"`
		Content    string `json:"content"`
		OperatorID string `json:"operator_id"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	if strings.TrimSpace(p.Content) == "" {
		writeAdminError(w, 400, "empty_chunk", "content must not be empty")
		return
	}
	if p.OperatorID != "" {
		if _, err := server.service.ClaimRequest(r.Context(), r.PathValue("id"), p.OperatorID); err != nil {
			server.writeRepositoryError(w, r, err)
			return
		}
	}
	chunk, created, err := server.service.AppendChunk(r.Context(), r.PathValue("id"), p.ChunkID, p.Content)
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	status := 200
	if created {
		status = 201
	}
	writeJSON(w, status, map[string]any{"chunk": chunk, "created": created})
}
func (server *Server) adminCompleteRequest(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.CompleteRequest(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, nil, true))
}
func (server *Server) adminAnswerRequest(w http.ResponseWriter, r *http.Request) {
	var p struct {
		ResponseType  string         `json:"response_type"`
		Content       string         `json:"content"`
		Text          string         `json:"text"`
		ToolName      string         `json:"tool_name"`
		ToolArguments map[string]any `json:"tool_arguments"`
		OperatorID    string         `json:"operator_id"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	var item domain.HumanRequest
	var err error
	if p.OperatorID != "" {
		if _, err = server.service.ClaimRequest(r.Context(), r.PathValue("id"), p.OperatorID); err != nil {
			server.writeRepositoryError(w, r, err)
			return
		}
	}
	if p.ResponseType == "tool_call" {
		item, err = server.service.AnswerTool(r.Context(), r.PathValue("id"), p.ToolName, p.ToolArguments)
	} else {
		content := p.Content
		if content == "" {
			content = p.Text
		}
		if strings.TrimSpace(content) == "" {
			writeAdminError(w, 400, "empty_answer", "content must not be empty")
			return
		}
		item, err = server.service.AnswerRequest(r.Context(), r.PathValue("id"), content)
	}
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, nil, true))
}
func (server *Server) adminClaimRequest(w http.ResponseWriter, r *http.Request) {
	var p struct {
		OperatorID string `json:"operator_id"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	item, err := server.service.ClaimRequest(r.Context(), r.PathValue("id"), p.OperatorID)
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, nil, false))
}
func (server *Server) adminReleaseClaim(w http.ResponseWriter, r *http.Request) {
	operator := r.URL.Query().Get("operator_id")
	if err := server.service.ReleaseClaim(r.Context(), r.PathValue("id"), operator); err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	w.WriteHeader(204)
}

func (server *Server) adminMarkRequestRead(w http.ResponseWriter, r *http.Request) {
	item, err := server.service.MarkRequestRead(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, nil, false))
}

func (server *Server) adminSaveRequestDraft(w http.ResponseWriter, r *http.Request) {
	var p struct {
		Content  string `json:"content"`
		DeviceID string `json:"device_id"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	if len([]rune(p.Content)) > 50000 {
		writeAdminError(w, 400, "draft_too_long", "draft must be at most 50000 characters")
		return
	}
	if p.DeviceID == "" {
		p.DeviceID, _ = r.Context().Value(contextKey("device-id")).(string)
	}
	item, err := server.service.SaveRequestDraft(r.Context(), r.PathValue("id"), p.Content, p.DeviceID)
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, adminRequest(item, nil, false))
}

func adminRequest(item domain.HumanRequest, chunks []domain.StreamChunk, detail bool) map[string]any {
	result := map[string]any{"id": item.ID, "model": item.Model, "preview": item.Preview, "status": item.Status, "mode": item.Mode, "source": item.Source, "conversation_id": item.ConversationID, "context_chars": item.ContextChars, "message_count": item.MessageCount, "system_count": item.SystemCount, "tool_count": item.ToolCount, "attachment_count": item.AttachmentCount, "stream_requested": item.StreamRequested, "stream_chunk_count": item.StreamChunkCount, "answer": item.Answer, "response": item.Response, "answer_source": item.AnswerSource, "auto_reply_label": item.AutoReplyLabel, "created_at": item.CreatedAt, "updated_at": item.UpdatedAt, "answered_at": item.AnsweredAt, "expires_at": item.ExpiresAt, "claim_owner": item.ClaimOwner, "claim_expires_at": item.ClaimExpiresAt, "client_online": item.ClientLastSeenAt > time.Now().Add(-20*time.Second).UnixMilli(), "read_at": item.ReadAt, "draft": item.Draft, "draft_updated_at": item.DraftUpdatedAt, "draft_device_id": item.DraftDeviceID}
	if detail {
		result["messages"] = visibleMessages(item.ID, item.Messages)
		result["tools"] = toolSummaries(item.Tools)
	}
	if chunks != nil {
		result["stream_chunks"] = chunks
	}
	return result
}
func visibleMessages(requestID string, messages []domain.Message) []domain.Message {
	result := []domain.Message{}
	for messageIndex, message := range messages {
		if message.Role != "user" && message.Role != "assistant" {
			continue
		}
		if message.Role == "assistant" && len(message.ToolCalls) > 0 {
			continue
		}
		if message.Role == "user" {
			text := domain.MessageText(message.Content)
			clean := domain.CleanUserText(text)
			if clean == "" {
				continue
			}
			if clean != text {
				encoded, _ := json.Marshal(clean)
				message.Content = encoded
			}
		}
		var parts []map[string]any
		if json.Unmarshal(message.Content, &parts) == nil {
			for partIndex := range parts {
				replaceAttachment(parts[partIndex], fmt.Sprintf("/admin/api/v1/requests/%s/attachments/%d/%d", requestID, messageIndex, partIndex))
			}
			message.Content, _ = json.Marshal(parts)
		}
		result = append(result, message)
	}
	return result
}
func attachmentValue(part map[string]any) string {
	if value, ok := part["image_url"].(string); ok {
		return value
	}
	if image, ok := part["image_url"].(map[string]any); ok {
		if value, ok := image["url"].(string); ok {
			return value
		}
	}
	if file, ok := part["file"].(map[string]any); ok {
		if value, ok := file["url"].(string); ok {
			return value
		}
	}
	return ""
}
func replaceAttachment(part map[string]any, replacement string) {
	value := attachmentValue(part)
	if !strings.HasPrefix(value, "data:") {
		return
	}
	if image, ok := part["image_url"].(map[string]any); ok {
		image["url"] = replacement
		return
	}
	if _, ok := part["image_url"].(string); ok {
		part["image_url"] = replacement
		return
	}
	if file, ok := part["file"].(map[string]any); ok {
		file["url"] = replacement
	}
}
func toolSummaries(tools []json.RawMessage) []any {
	result := []any{}
	for _, raw := range tools {
		var tool map[string]any
		if json.Unmarshal(raw, &tool) != nil {
			continue
		}
		summary := map[string]any{"type": tool["type"]}
		if function, ok := tool["function"].(map[string]any); ok {
			description := fmt.Sprint(function["description"])
			runes := []rune(description)
			if len(runes) > 500 {
				description = string(runes[:499]) + "…"
			}
			parameterCount := 0
			if parameters, ok := function["parameters"].(map[string]any); ok {
				if properties, ok := parameters["properties"].(map[string]any); ok {
					parameterCount = len(properties)
				}
			}
			summary["function"] = map[string]any{"name": function["name"], "description": description, "parameter_count": parameterCount, "schema_available_in_raw": true}
		}
		result = append(result, summary)
	}
	return result
}

func (server *Server) writeRepositoryError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeAdminError(w, 404, "not_found", "Resource not found")
	case errors.Is(err, repository.ErrNotPending):
		writeAdminError(w, 409, "request_not_pending", "Request is no longer pending")
	case errors.Is(err, repository.ErrNoStreamChunks):
		writeAdminError(w, 409, "no_stream_chunks", "Send at least one chunk before completing the request")
	case errors.Is(err, repository.ErrHasStreamChunks):
		writeAdminError(w, 409, "has_stream_chunks", "Complete the existing stream instead of replacing it")
	case errors.Is(err, repository.ErrClaimed):
		writeAdminError(w, 409, "request_claimed", "Request is being answered on another device")
	default:
		server.internalError(w, r, err)
	}
}
