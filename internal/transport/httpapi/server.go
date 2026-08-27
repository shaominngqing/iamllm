package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"log/slog"
	"mime"
	"net"
	"net/http"
	"path"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"

	"iamllm/internal/application"
	"iamllm/internal/buildinfo"
	"iamllm/internal/config"
	"iamllm/internal/webassets"
)

type contextKey string

const principalKey contextKey = "api-principal"

type Server struct {
	config  config.Config
	service *application.Service
	control *application.ControlService
	logger  *slog.Logger
	mux     *http.ServeMux
	web     fs.FS
	loginMu sync.Mutex
	logins  map[string]loginAttempt
}

type loginAttempt struct {
	Failures int
	ResetAt  time.Time
}

func New(config config.Config, service *application.Service, control *application.ControlService, logger *slog.Logger) *Server {
	assets, _ := fs.Sub(webassets.Dist, "dist")
	server := &Server{config: config, service: service, control: control, logger: logger, mux: http.NewServeMux(), web: assets, logins: map[string]loginAttempt{}}
	server.routes()
	return server
}

func (server *Server) Handler() http.Handler {
	return server.securityHeaders(server.recoverPanic(server.logRequest(server.mux)))
}

func (server *Server) routes() {
	server.mux.HandleFunc("GET /", server.root)
	server.mux.HandleFunc("GET /health", server.health)
	server.mux.HandleFunc("GET /openapi.json", server.openAPI)
	server.mux.HandleFunc("GET /admin", server.webApp)
	server.mux.HandleFunc("GET /admin/", server.webApp)
	server.mux.HandleFunc("GET /playground", server.webApp)
	server.mux.HandleFunc("GET /favicon.svg", server.webRootAsset)
	server.mux.HandleFunc("GET /assets/{path...}", server.webAsset)

	server.mux.Handle("GET /v1/models", server.requireAPIKey(false, http.HandlerFunc(server.models)))
	server.mux.Handle("GET /v1/models/{model}", server.requireAPIKey(false, http.HandlerFunc(server.model)))
	server.mux.Handle("POST /v1/chat/completions", server.requireAPIKey(true, http.HandlerFunc(server.chatCompletions)))
	server.mux.Handle("POST /v1/responses", server.requireAPIKey(true, http.HandlerFunc(server.responses)))
	server.mux.Handle("GET /v1/responses/{id}", server.requireAPIKey(false, http.HandlerFunc(server.responseStatus)))
	server.mux.Handle("POST /v1/messages", server.requireAPIKey(true, http.HandlerFunc(server.anthropicMessages)))
	server.mux.Handle("POST /v1/messages/count_tokens", server.requireAPIKey(false, http.HandlerFunc(server.anthropicCountTokens)))
	server.mux.Handle("POST /v1beta/models/{action}", server.requireAPIKey(true, http.HandlerFunc(server.geminiGenerate)))
	server.mux.Handle("POST /v1/models/{action}", server.requireAPIKey(true, http.HandlerFunc(server.geminiGenerate)))
	server.mux.Handle("POST /v1/human/jobs", server.requireAPIKey(true, http.HandlerFunc(server.createJob)))
	server.mux.Handle("GET /v1/human/jobs/{id}", server.requireAPIKey(false, http.HandlerFunc(server.getJob)))

	server.mux.HandleFunc("POST /admin/api/v1/auth/login", server.adminLogin)
	server.mux.HandleFunc("POST /admin/api/v1/auth/pair", server.adminPair)
	server.mux.HandleFunc("POST /admin/api/v1/auth/refresh", server.adminRefresh)
	server.mux.Handle("GET /admin/api/v1/overview", server.requireAdmin(http.HandlerFunc(server.adminOverview)))
	server.mux.Handle("GET /admin/api/v1/events", server.requireAdmin(http.HandlerFunc(server.adminEvents)))
	server.mux.Handle("GET /admin/api/v1/requests", server.requireAdmin(http.HandlerFunc(server.adminRequests)))
	server.mux.Handle("GET /admin/api/v1/requests/{id}", server.requireAdmin(http.HandlerFunc(server.adminRequest)))
	server.mux.Handle("GET /admin/api/v1/requests/{id}/raw", server.requireAdmin(http.HandlerFunc(server.adminRawRequest)))
	server.mux.Handle("GET /admin/api/v1/requests/{id}/attachments/{message}/{part}", server.requireAdmin(http.HandlerFunc(server.adminAttachment)))
	server.mux.Handle("POST /admin/api/v1/requests/{id}/chunks", server.requireAdmin(http.HandlerFunc(server.adminAppendChunk)))
	server.mux.Handle("POST /admin/api/v1/requests/{id}/complete", server.requireAdmin(http.HandlerFunc(server.adminCompleteRequest)))
	server.mux.Handle("POST /admin/api/v1/requests/{id}/answer", server.requireAdmin(http.HandlerFunc(server.adminAnswerRequest)))
	server.mux.Handle("POST /admin/api/v1/requests/{id}/claim", server.requireAdmin(http.HandlerFunc(server.adminClaimRequest)))
	server.mux.Handle("DELETE /admin/api/v1/requests/{id}/claim", server.requireAdmin(http.HandlerFunc(server.adminReleaseClaim)))
	server.mux.Handle("PUT /admin/api/v1/requests/{id}/read", server.requireAdmin(http.HandlerFunc(server.adminMarkRequestRead)))
	server.mux.Handle("PUT /admin/api/v1/requests/{id}/draft", server.requireAdmin(http.HandlerFunc(server.adminSaveRequestDraft)))
	server.mux.Handle("POST /admin/api/v1/playground/chat/completions", server.requireAdmin(http.HandlerFunc(server.adminPlaygroundChat)))
	server.mux.Handle("GET /admin/api/v1/profile", server.requireAdmin(http.HandlerFunc(server.adminProfile)))
	server.mux.Handle("PUT /admin/api/v1/profile", server.requireAdmin(http.HandlerFunc(server.adminSaveProfile)))
	server.mux.Handle("GET /admin/api/v1/quick-replies", server.requireAdmin(http.HandlerFunc(server.adminQuickReplies)))
	server.mux.Handle("POST /admin/api/v1/quick-replies", server.requireAdmin(http.HandlerFunc(server.adminCreateQuickReply)))
	server.mux.Handle("PATCH /admin/api/v1/quick-replies/{id}", server.requireAdmin(http.HandlerFunc(server.adminUpdateQuickReply)))
	server.mux.Handle("DELETE /admin/api/v1/quick-replies/{id}", server.requireAdmin(http.HandlerFunc(server.adminDeleteQuickReply)))
	server.mux.Handle("GET /admin/api/v1/auto-rules", server.requireAdmin(http.HandlerFunc(server.adminAutoRules)))
	server.mux.Handle("POST /admin/api/v1/auto-rules", server.requireAdmin(http.HandlerFunc(server.adminCreateAutoRule)))
	server.mux.Handle("POST /admin/api/v1/auto-rules/preview", server.requireAdmin(http.HandlerFunc(server.adminPreviewAutoRule)))
	server.mux.Handle("PATCH /admin/api/v1/auto-rules/{id}", server.requireAdmin(http.HandlerFunc(server.adminUpdateAutoRule)))
	server.mux.Handle("DELETE /admin/api/v1/auto-rules/{id}", server.requireAdmin(http.HandlerFunc(server.adminDeleteAutoRule)))
	server.mux.Handle("GET /admin/api/v1/api-keys", server.requireAdmin(http.HandlerFunc(server.adminAPIKeys)))
	server.mux.Handle("POST /admin/api/v1/api-keys", server.requireAdmin(http.HandlerFunc(server.adminCreateAPIKey)))
	server.mux.Handle("PATCH /admin/api/v1/api-keys/{id}", server.requireAdmin(http.HandlerFunc(server.adminUpdateAPIKey)))
	server.mux.Handle("POST /admin/api/v1/api-keys/{id}/revoke", server.requireAdmin(http.HandlerFunc(server.adminRevokeAPIKey)))
	server.mux.Handle("POST /admin/api/v1/pairing-codes", server.requireAdmin(http.HandlerFunc(server.adminPairingCode)))
	server.mux.Handle("GET /admin/api/v1/devices", server.requireAdmin(http.HandlerFunc(server.adminDevices)))
	server.mux.Handle("PUT /admin/api/v1/devices/self", server.requireAdmin(http.HandlerFunc(server.adminUpdateCurrentDevice)))
	server.mux.Handle("DELETE /admin/api/v1/devices/{id}", server.requireAdmin(http.HandlerFunc(server.adminRevokeDevice)))
}

func (server *Server) root(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, "/admin", http.StatusTemporaryRedirect)
}
func (server *Server) health(w http.ResponseWriter, r *http.Request) {
	pending, err := server.service.PendingCount(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "runtime": "go", "version": buildinfo.Version, "model": server.config.ModelName, "pending": pending, "capabilities": []string{"openai_chat_completions", "openai_responses", "anthropic_messages", "gemini_generate_content", "streaming", "vision", "function_calling", "admin_sse", "device_pairing"}})
}

func (server *Server) requireAPIKey(count bool, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		secret := bearerToken(r)
		if secret == "" {
			secret = strings.TrimSpace(r.Header.Get("x-api-key"))
		}
		if secret == "" {
			secret = strings.TrimSpace(r.Header.Get("x-goog-api-key"))
		}
		if secret == "" {
			secret = strings.TrimSpace(r.URL.Query().Get("key"))
		}
		metered := count && !strings.HasSuffix(r.PathValue("action"), ":countTokens")
		principal, err := server.control.AuthenticateAPIKey(r.Context(), secret, metered)
		if limit, ok := err.(application.LimitError); ok {
			w.Header().Set("Retry-After", strconv.Itoa(limit.RetryAfter))
			server.writeProtocolError(w, r, http.StatusTooManyRequests, "rate_limit_error", limit.Error())
			return
		}
		if err != nil {
			server.writeProtocolError(w, r, http.StatusUnauthorized, "authentication_error", "Invalid API key")
			return
		}
		ctx := context.WithValue(r.Context(), principalKey, principal)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
func (server *Server) requireAdmin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := strings.TrimSpace(r.Header.Get("X-Admin-Token"))
		if token == "" {
			token = bearerToken(r)
		}
		if server.control.IsMasterAdmin(token) {
			next.ServeHTTP(w, r)
			return
		}
		deviceID, err := server.control.ValidateAccess(token)
		if err != nil {
			writeAdminError(w, http.StatusUnauthorized, "invalid_admin_token", "管理登录已失效，请重新登录")
			return
		}
		_ = server.control.TouchDevice(r.Context(), deviceID, requestIP(r), strings.TrimSpace(r.UserAgent()))
		ctx := context.WithValue(r.Context(), contextKey("device-id"), deviceID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func requestIP(r *http.Request) string {
	if forwarded := strings.TrimSpace(strings.Split(r.Header.Get("X-Forwarded-For"), ",")[0]); forwarded != "" {
		return forwarded
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}
func apiKeyID(r *http.Request) string {
	if value, ok := r.Context().Value(principalKey).(application.APIPrincipal); ok {
		return value.ID
	}
	return ""
}

func requestOwnedBy(r *http.Request, item applicationRequestOwner) bool {
	owner, principal := item.OwnerAPIKeyID(), apiKeyID(r)
	return owner != "" && owner == principal
}

type applicationRequestOwner interface {
	OwnerAPIKeyID() string
}

func (server *Server) webApp(w http.ResponseWriter, r *http.Request) {
	data, err := fs.ReadFile(server.web, "index.html")
	if err != nil {
		http.Error(w, "console unavailable", 500)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write(data)
}
func (server *Server) webAsset(w http.ResponseWriter, r *http.Request) {
	name := "assets/" + path.Clean(r.PathValue("path"))
	data, err := fs.ReadFile(server.web, name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	if value := mime.TypeByExtension(path.Ext(name)); value != "" {
		w.Header().Set("Content-Type", value)
	}
	w.Header().Set("Cache-Control", "public,max-age=31536000,immutable")
	_, _ = w.Write(data)
}
func (server *Server) webRootAsset(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
	data, err := fs.ReadFile(server.web, name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	if value := mime.TypeByExtension(path.Ext(name)); value != "" {
		w.Header().Set("Content-Type", value)
	}
	w.Header().Set("Cache-Control", "public,max-age=86400")
	_, _ = w.Write(data)
}
func bearerToken(r *http.Request) string {
	value := strings.TrimSpace(r.Header.Get("Authorization"))
	if len(value) < 8 || !strings.EqualFold(value[:7], "Bearer ") {
		return ""
	}
	return strings.TrimSpace(value[7:])
}
func secureEqual(first, second string) bool {
	if len(first) != len(second) || len(first) == 0 {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(first), []byte(second)) == 1
}
func (server *Server) internalError(w http.ResponseWriter, r *http.Request, err error) {
	server.logger.Error("request failed", "method", r.Method, "path", r.URL.Path, "error", err)
	writeJSON(w, 500, map[string]any{"error": map[string]string{"code": "internal_error", "message": "Internal server error"}})
}
func (server *Server) recoverPanic(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				server.logger.Error("panic recovered", "error", recovered, "stack", string(debug.Stack()))
				writeJSON(w, 500, map[string]any{"error": map[string]string{"code": "internal_error", "message": "Internal server error"}})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (w *statusRecorder) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}
func (w *statusRecorder) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}
func (server *Server) logRequest(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: 200}
		next.ServeHTTP(rec, r)
		server.logger.Info("http request", "method", r.Method, "path", r.URL.Path, "status", rec.status, "duration_ms", time.Since(start).Milliseconds())
	})
}
func (server *Server) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self'; script-src 'self'; connect-src 'self'")
		if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
			w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		}
		if strings.HasPrefix(r.URL.Path, "/admin/api/") {
			w.Header().Set("Cache-Control", "no-store")
		}
		next.ServeHTTP(w, r)
	})
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func decodeJSON(w http.ResponseWriter, r *http.Request, destination any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 12<<20)
	decoder := json.NewDecoder(r.Body)
	decoder.UseNumber()
	if err := decoder.Decode(destination); err != nil {
		writeJSON(w, 400, map[string]any{"error": map[string]string{"code": "invalid_json", "message": "Request body must be valid JSON"}})
		return false
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		writeJSON(w, 400, map[string]any{"error": map[string]string{"code": "invalid_json", "message": "Request body must contain one JSON value"}})
		return false
	}
	return true
}
func writeAdminError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}
func (server *Server) writeProtocolError(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	if r.URL.Path == "/v1/messages" || strings.HasPrefix(r.URL.Path, "/v1/messages/") {
		writeJSON(w, status, map[string]any{"type": "error", "error": map[string]any{"type": code, "message": message}})
		return
	}
	if strings.Contains(r.URL.Path, "generateContent") || strings.Contains(r.URL.Path, "countTokens") {
		writeJSON(w, status, map[string]any{"error": map[string]any{"code": status, "message": message, "status": strings.ToUpper(code)}})
		return
	}
	writeOpenAIError(w, status, code, message)
}
func writeOpenAIError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]any{"message": message, "type": code, "param": nil, "code": code}})
}
