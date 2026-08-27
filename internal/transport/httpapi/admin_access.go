package httpapi

import (
	"encoding/json"
	"net"
	"net/http"
	"net/url"
	"strings"

	"iamllm/internal/domain"
)

func (server *Server) adminAPIKeys(w http.ResponseWriter, r *http.Request) {
	items, err := server.control.ListAPIKeys(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	result := []any{map[string]any{
		"id": "master", "name": "环境变量总钥匙", "key_hint": secretHint(server.config.APIKey),
		"active": true, "is_master": true, "rate_limit_per_minute": 0, "daily_limit": 0,
		"max_concurrent": 0, "usage_minute": 0, "usage_today": 0, "pending_requests": 0,
	}}
	for _, item := range items {
		result = append(result, item)
	}
	writeJSON(w, 200, map[string]any{"items": result})
}

func secretHint(value string) string {
	if len(value) <= 12 {
		return "sk-••••••••"
	}
	return value[:6] + "••••••••" + value[len(value)-4:]
}
func (server *Server) adminCreateAPIKey(w http.ResponseWriter, r *http.Request) {
	var p struct {
		Name       string `json:"name"`
		Rate       int    `json:"rate_limit_per_minute"`
		Daily      int    `json:"daily_limit"`
		Concurrent int    `json:"max_concurrent"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	if p.Rate == 0 {
		p.Rate = 10
	}
	if p.Daily == 0 {
		p.Daily = 100
	}
	if p.Concurrent == 0 {
		p.Concurrent = 3
	}
	if strings.TrimSpace(p.Name) == "" || p.Rate < 1 || p.Rate > 10000 || p.Daily < 1 || p.Daily > 1000000 || p.Concurrent < 1 || p.Concurrent > 1000 {
		writeAdminError(w, 400, "invalid_api_key", "name and positive, reasonable limits are required")
		return
	}
	secret, item, err := server.control.CreateAPIKey(r.Context(), p.Name, p.Rate, p.Daily, p.Concurrent)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 201, map[string]any{"key": secret, "item": item, "base_url": publicBase(server.config.PublicBaseURL, r), "model": server.config.ModelName})
}
func (server *Server) adminUpdateAPIKey(w http.ResponseWriter, r *http.Request) {
	item, err := server.control.GetAPIKey(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	var values map[string]any
	if !decodeJSON(w, r, &values) {
		return
	}
	mergeJSON(values, &item)
	if strings.TrimSpace(item.Name) == "" || item.RateLimitPerMinute < 1 || item.DailyLimit < 1 || item.MaxConcurrent < 1 {
		writeAdminError(w, 400, "invalid_api_key", "name and positive limits are required")
		return
	}
	saved, err := server.control.SaveAPIKey(r.Context(), item)
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, saved)
}
func (server *Server) adminRevokeAPIKey(w http.ResponseWriter, r *http.Request) {
	item, err := server.control.RevokeAPIKey(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	writeJSON(w, 200, item)
}

func (server *Server) adminPairingCode(w http.ResponseWriter, r *http.Request) {
	var p struct {
		Label string `json:"label"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	code, expires, err := server.control.CreatePairing(r.Context(), p.Label)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	serverURL := publicBase(server.config.PublicBaseURL, r)
	writeJSON(w, 201, map[string]any{
		"code":        code,
		"expires_at":  expires,
		"server_url":  serverURL,
		"pairing_uri": pairingURI(serverURL, code),
	})
}
func (server *Server) adminDevices(w http.ResponseWriter, r *http.Request) {
	items, err := server.control.Devices(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	currentDeviceID, _ := r.Context().Value(contextKey("device-id")).(string)
	writeJSON(w, 200, map[string]any{"items": items, "current_device_id": currentDeviceID})
}

func (server *Server) adminUpdateCurrentDevice(w http.ResponseWriter, r *http.Request) {
	deviceID, _ := r.Context().Value(contextKey("device-id")).(string)
	if deviceID == "" {
		writeAdminError(w, 400, "managed_device_required", "环境总钥匙没有可更新的设备档案")
		return
	}
	var p struct {
		DeviceName  string `json:"device_name"`
		Platform    string `json:"platform"`
		DeviceModel string `json:"device_model"`
		OSVersion   string `json:"os_version"`
		AppVersion  string `json:"app_version"`
		Locale      string `json:"locale"`
		Timezone    string `json:"timezone"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	item := deviceFromRequest(r, p.DeviceName, p.Platform, p.DeviceModel, p.OSVersion, p.AppVersion, p.Locale, p.Timezone)
	if err := server.control.UpdateDeviceMetadata(r.Context(), deviceID, item); err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
func (server *Server) adminRevokeDevice(w http.ResponseWriter, r *http.Request) {
	if err := server.control.RevokeDevice(r.Context(), r.PathValue("id")); err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	w.WriteHeader(204)
}
func mergeJSON(values map[string]any, target any) {
	encoded, _ := json.Marshal(values)
	_ = json.Unmarshal(encoded, target)
}
func publicBase(configured string, r *http.Request) string {
	if configured != "" {
		return configured
	}
	scheme := "http"
	if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
		scheme = "https"
	}
	return scheme + "://" + r.Host
}

func pairingURI(serverURL, code string) string {
	pair := url.URL{Scheme: "iamllm", Host: "pair"}
	query := pair.Query()
	query.Set("server", serverURL)
	query.Set("code", code)
	pair.RawQuery = query.Encode()
	return pair.String()
}

func deviceFromRequest(r *http.Request, name, platform, model, osVersion, appVersion, locale, timezone string) domain.AdminDevice {
	host := r.RemoteAddr
	if value, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		host = value
	}
	return domain.AdminDevice{
		Name: strings.TrimSpace(name), Platform: strings.TrimSpace(platform),
		DeviceModel: strings.TrimSpace(model), OSVersion: strings.TrimSpace(osVersion),
		AppVersion: strings.TrimSpace(appVersion), Locale: strings.TrimSpace(locale),
		Timezone: strings.TrimSpace(timezone), IPAddress: host, UserAgent: strings.TrimSpace(r.UserAgent()),
	}
}
