package httpapi

import (
	"net"
	"net/http"
	"time"
)

type loginPayload struct {
	Username    string `json:"username"`
	Password    string `json:"password"`
	DeviceName  string `json:"device_name"`
	Platform    string `json:"platform"`
	DeviceModel string `json:"device_model"`
	OSVersion   string `json:"os_version"`
	AppVersion  string `json:"app_version"`
	Locale      string `json:"locale"`
	Timezone    string `json:"timezone"`
}
type pairPayload struct {
	Code        string `json:"code"`
	DeviceName  string `json:"device_name"`
	Platform    string `json:"platform"`
	DeviceModel string `json:"device_model"`
	OSVersion   string `json:"os_version"`
	AppVersion  string `json:"app_version"`
	Locale      string `json:"locale"`
	Timezone    string `json:"timezone"`
}
type refreshPayload struct {
	RefreshToken string `json:"refresh_token"`
	DeviceName   string `json:"device_name"`
	Platform     string `json:"platform"`
	DeviceModel  string `json:"device_model"`
	OSVersion    string `json:"os_version"`
	AppVersion   string `json:"app_version"`
	Locale       string `json:"locale"`
	Timezone     string `json:"timezone"`
}

func (server *Server) adminLogin(w http.ResponseWriter, r *http.Request) {
	client := r.RemoteAddr
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		client = host
	}
	if !server.allowAdminLogin(client) {
		w.Header().Set("Retry-After", "900")
		writeAdminError(w, http.StatusTooManyRequests, "login_rate_limited", "登录尝试太频繁，请稍后再试")
		return
	}
	var p loginPayload
	if !decodeJSON(w, r, &p) {
		return
	}
	pair, err := server.control.Login(r.Context(), p.Username, p.Password, deviceFromRequest(r, p.DeviceName, p.Platform, p.DeviceModel, p.OSVersion, p.AppVersion, p.Locale, p.Timezone))
	if err != nil {
		server.recordAdminLoginFailure(client)
		writeAdminError(w, 401, "invalid_credentials", "用户名或密码不正确")
		return
	}
	server.clearAdminLoginFailures(client)
	writeJSON(w, 200, pair)
}

func (server *Server) allowAdminLogin(client string) bool {
	server.loginMu.Lock()
	defer server.loginMu.Unlock()
	attempt := server.logins[client]
	if time.Now().After(attempt.ResetAt) {
		delete(server.logins, client)
		return true
	}
	return attempt.Failures < 8
}

func (server *Server) recordAdminLoginFailure(client string) {
	server.loginMu.Lock()
	defer server.loginMu.Unlock()
	attempt := server.logins[client]
	if time.Now().After(attempt.ResetAt) {
		attempt = loginAttempt{ResetAt: time.Now().Add(15 * time.Minute)}
	}
	attempt.Failures++
	server.logins[client] = attempt
}

func (server *Server) clearAdminLoginFailures(client string) {
	server.loginMu.Lock()
	delete(server.logins, client)
	server.loginMu.Unlock()
}
func (server *Server) adminPair(w http.ResponseWriter, r *http.Request) {
	var p pairPayload
	if !decodeJSON(w, r, &p) {
		return
	}
	pair, err := server.control.Pair(r.Context(), p.Code, deviceFromRequest(r, p.DeviceName, p.Platform, p.DeviceModel, p.OSVersion, p.AppVersion, p.Locale, p.Timezone))
	if err != nil {
		writeAdminError(w, 401, "invalid_pairing_code", "配对码无效或已过期")
		return
	}
	writeJSON(w, 200, pair)
}
func (server *Server) adminRefresh(w http.ResponseWriter, r *http.Request) {
	var p refreshPayload
	if !decodeJSON(w, r, &p) {
		return
	}
	pair, err := server.control.Refresh(r.Context(), p.RefreshToken, deviceFromRequest(r, p.DeviceName, p.Platform, p.DeviceModel, p.OSVersion, p.AppVersion, p.Locale, p.Timezone))
	if err != nil {
		writeAdminError(w, 401, "invalid_refresh_token", "设备登录已失效")
		return
	}
	writeJSON(w, 200, pair)
}
