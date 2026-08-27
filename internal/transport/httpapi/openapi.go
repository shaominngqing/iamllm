package httpapi

import (
	"net/http"

	"iamllm/internal/buildinfo"
)

func (server *Server) openAPI(w http.ResponseWriter, _ *http.Request) {
	baseURL := server.config.PublicBaseURL
	if baseURL == "" {
		baseURL = "/"
	}
	security := []any{map[string]any{"bearerAuth": []any{}}, map[string]any{"apiKey": []any{}}}
	adminSecurity := []any{map[string]any{"adminBearer": []any{}}}
	paths := map[string]any{
		"/v1/models":                                   map[string]any{"get": operation("List compatible models", security)},
		"/v1/chat/completions":                         map[string]any{"post": operation("OpenAI Chat Completions; streaming supported", security)},
		"/v1/responses":                                map[string]any{"post": operation("OpenAI Responses; streaming and background supported", security)},
		"/v1/responses/{id}":                           map[string]any{"get": operation("Retrieve a background response", security)},
		"/v1/messages":                                 map[string]any{"post": operation("Anthropic Messages; streaming supported", security)},
		"/v1/messages/count_tokens":                    map[string]any{"post": operation("Estimate Anthropic input tokens", security)},
		"/v1beta/models/{model}:generateContent":       map[string]any{"post": operation("Gemini GenerateContent", security)},
		"/v1beta/models/{model}:streamGenerateContent": map[string]any{"post": operation("Gemini streaming GenerateContent", security)},
		"/v1beta/models/{model}:countTokens":           map[string]any{"post": operation("Estimate Gemini input tokens", security)},
		"/v1/human/jobs":                               map[string]any{"post": operation("Create an asynchronous human job", security)},
		"/v1/human/jobs/{id}":                          map[string]any{"get": operation("Retrieve a human job", security)},
		"/admin/api/v1/auth/login":                     map[string]any{"post": operation("Create a web admin device session", nil)},
		"/admin/api/v1/auth/pair":                      map[string]any{"post": operation("Pair a device with a one-time code", nil)},
		"/admin/api/v1/auth/refresh":                   map[string]any{"post": operation("Rotate a device refresh token", nil)},
		"/admin/api/v1/events":                         map[string]any{"get": operation("Recoverable admin SSE event stream", adminSecurity)},
		"/admin/api/v1/requests":                       map[string]any{"get": operation("List request summaries with cursor pagination", adminSecurity)},
		"/admin/api/v1/requests/{id}":                  map[string]any{"get": operation("Get a user-visible request detail", adminSecurity)},
		"/admin/api/v1/requests/{id}/raw":              map[string]any{"get": operation("Lazily load full raw context", adminSecurity)},
		"/admin/api/v1/requests/{id}/chunks":           map[string]any{"post": operation("Append an idempotent response chunk", adminSecurity)},
		"/admin/api/v1/requests/{id}/complete":         map[string]any{"post": operation("Complete a chunked response", adminSecurity)},
		"/admin/api/v1/requests/{id}/answer":           map[string]any{"post": operation("Return one text response or tool call", adminSecurity)},
		"/admin/api/v1/requests/{id}/read":             map[string]any{"put": operation("Synchronize the shared request read state", adminSecurity)},
		"/admin/api/v1/requests/{id}/draft":            map[string]any{"put": operation("Synchronize a reply draft across admin devices", adminSecurity)},
		"/admin/api/v1/playground/chat/completions":    map[string]any{"post": operation("Run an authenticated console test chat using server-side configuration", adminSecurity)},
		"/admin/api/v1/quick-replies":                  map[string]any{"get": operation("List quick replies", adminSecurity), "post": operation("Create a quick reply", adminSecurity)},
		"/admin/api/v1/auto-rules":                     map[string]any{"get": operation("List auto-reply rules", adminSecurity), "post": operation("Create an auto-reply rule", adminSecurity)},
		"/admin/api/v1/api-keys":                       map[string]any{"get": operation("List API key summaries", adminSecurity), "post": operation("Create a managed API key", adminSecurity)},
		"/admin/api/v1/pairing-codes":                  map[string]any{"post": operation("Create a one-time device pairing code", adminSecurity)},
		"/admin/api/v1/devices":                        map[string]any{"get": operation("List admin devices", adminSecurity)},
		"/admin/api/v1/devices/self":                   map[string]any{"put": operation("Upload metadata for the current admin device", adminSecurity)},
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"openapi": "3.1.0",
		"info":    map[string]any{"title": "iamllm API", "version": buildinfo.Version, "description": "Wrap a human as an OpenAI, Anthropic, or Gemini compatible model."},
		"servers": []any{map[string]any{"url": baseURL}},
		"components": map[string]any{"securitySchemes": map[string]any{
			"bearerAuth":  map[string]any{"type": "http", "scheme": "bearer"},
			"apiKey":      map[string]any{"type": "apiKey", "in": "header", "name": "x-api-key"},
			"adminBearer": map[string]any{"type": "http", "scheme": "bearer", "description": "Short-lived admin device access token"},
		}},
		"paths": paths,
	})
}

func operation(summary string, security []any) map[string]any {
	return map[string]any{
		"summary":  summary,
		"security": security,
		"responses": map[string]any{
			"200": map[string]any{"description": "Success"},
			"400": map[string]any{"description": "Invalid request"},
			"401": map[string]any{"description": "Invalid API key"},
			"429": map[string]any{"description": "Rate limit exceeded"},
		},
	}
}
