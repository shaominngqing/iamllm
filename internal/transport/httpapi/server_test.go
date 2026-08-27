package httpapi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"iamllm/internal/application"
	"iamllm/internal/config"
	"iamllm/internal/repository/sqlite"
	"iamllm/internal/transport/httpapi"
)

func TestOpenAIStreamThroughAdminChunkAPI(t *testing.T) {
	store, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "iamllm.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()
	settings := config.Config{
		Environment:      "test",
		APIKey:           "test-api-key",
		AdminAPIToken:    "test-admin-token",
		ModelName:        "human-test",
		ResponseTimeout:  3 * time.Second,
		JobTTL:           time.Hour,
		PollInterval:     5 * time.Millisecond,
		StreamIdle:       time.Minute,
		TimeoutFallbacks: []string{"timeout"},
		SessionSecret:    "test-session-secret",
		AdminUsername:    "admin",
		AdminPassword:    "test-password",
	}
	service := application.New(store, application.Options{
		JobTTL:           settings.JobTTL,
		ResponseTimeout:  settings.ResponseTimeout,
		PollInterval:     settings.PollInterval,
		StreamIdle:       settings.StreamIdle,
		TimeoutFallbacks: settings.TimeoutFallbacks,
	})
	control := application.NewControl(store, application.ControlOptions{MasterAPIKey: settings.APIKey, AdminToken: settings.AdminAPIToken, AdminUsername: settings.AdminUsername, AdminPassword: settings.AdminPassword, SessionSecret: settings.SessionSecret})
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	testServer := httptest.NewServer(httpapi.New(settings, service, control, logger).Handler())
	defer testServer.Close()

	requestBody := `{"model":"gpt-4-compatible","stream":true,"messages":[{"role":"user","content":"你好"}]}`
	request, _ := http.NewRequest(http.MethodPost, testServer.URL+"/v1/chat/completions", strings.NewReader(requestBody))
	request.Header.Set("Authorization", "Bearer test-api-key")
	request.Header.Set("Content-Type", "application/json")
	response, err := testServer.Client().Do(request)
	if err != nil {
		t.Fatalf("start stream: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("start stream status=%d body=%s", response.StatusCode, body)
	}
	requestID := response.Header.Get("X-Human-Request-ID")
	if requestID == "" {
		t.Fatal("missing X-Human-Request-ID")
	}

	appendChunk(t, testServer, requestID, "chunk-1", "你", http.StatusCreated)
	appendChunk(t, testServer, requestID, "chunk-1", "你", http.StatusOK)
	appendChunk(t, testServer, requestID, "chunk-2", "好", http.StatusCreated)
	adminPost(t, testServer, "/admin/api/v1/requests/"+requestID+"/complete", `{}`, http.StatusOK)

	streamed, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read stream: %v", err)
	}
	text := string(streamed)
	if !strings.Contains(text, `"content":"你"`) || !strings.Contains(text, `"content":"好"`) {
		t.Fatalf("missing streamed chunks: %s", text)
	}
	if !strings.Contains(text, "data: [DONE]") {
		t.Fatalf("missing stream completion: %s", text)
	}

	detailRequest, _ := http.NewRequest(http.MethodGet, testServer.URL+"/admin/api/v1/requests/"+requestID, nil)
	detailRequest.Header.Set("X-Admin-Token", "test-admin-token")
	detailResponse, err := testServer.Client().Do(detailRequest)
	if err != nil {
		t.Fatalf("get request detail: %v", err)
	}
	defer detailResponse.Body.Close()
	var detail map[string]any
	if err := json.NewDecoder(detailResponse.Body).Decode(&detail); err != nil {
		t.Fatalf("decode request detail: %v", err)
	}
	if detail["answer"] != "你好" || detail["status"] != "answered" {
		t.Fatalf("unexpected request detail: %#v", detail)
	}

	playgroundBody := `{"model":"must-be-ignored","stream":true,"messages":[{"role":"user","content":"Playground test"}]}`
	playgroundRequest, _ := http.NewRequest(http.MethodPost, testServer.URL+"/admin/api/v1/playground/chat/completions", strings.NewReader(playgroundBody))
	playgroundRequest.Header.Set("X-Admin-Token", "test-admin-token")
	playgroundRequest.Header.Set("Content-Type", "application/json")
	playgroundResponse, err := testServer.Client().Do(playgroundRequest)
	if err != nil {
		t.Fatalf("start playground stream: %v", err)
	}
	defer playgroundResponse.Body.Close()
	if playgroundResponse.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(playgroundResponse.Body)
		t.Fatalf("playground status=%d body=%s", playgroundResponse.StatusCode, body)
	}
	playgroundID := playgroundResponse.Header.Get("X-Human-Request-ID")
	if playgroundID == "" {
		t.Fatal("playground request omitted request id")
	}
	appendChunk(t, testServer, playgroundID, "playground-chunk", "OK", http.StatusCreated)
	adminPost(t, testServer, "/admin/api/v1/requests/"+playgroundID+"/complete", `{}`, http.StatusOK)
	playgroundStream, err := io.ReadAll(playgroundResponse.Body)
	if err != nil || !strings.Contains(string(playgroundStream), `"content":"OK"`) {
		t.Fatalf("unexpected playground stream: body=%s err=%v", playgroundStream, err)
	}

	playgroundDetailRequest, _ := http.NewRequest(http.MethodGet, testServer.URL+"/admin/api/v1/requests/"+playgroundID, nil)
	playgroundDetailRequest.Header.Set("X-Admin-Token", "test-admin-token")
	playgroundDetailResponse, err := testServer.Client().Do(playgroundDetailRequest)
	if err != nil {
		t.Fatalf("get playground detail: %v", err)
	}
	defer playgroundDetailResponse.Body.Close()
	var playgroundDetail map[string]any
	if err := json.NewDecoder(playgroundDetailResponse.Body).Decode(&playgroundDetail); err != nil {
		t.Fatalf("decode playground detail: %v", err)
	}
	if playgroundDetail["model"] != "human-test" || playgroundDetail["source"] != "web_chat" {
		t.Fatalf("playground did not use server configuration: %#v", playgroundDetail)
	}
}

func TestModelListRequiresAPIKey(t *testing.T) {
	store, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "iamllm.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()
	settings := config.Config{APIKey: "key", AdminAPIToken: "admin", ModelName: "human", SessionSecret: "secret", AdminUsername: "admin", AdminPassword: "password"}
	service := application.New(store, application.Options{})
	control := application.NewControl(store, application.ControlOptions{MasterAPIKey: settings.APIKey, AdminToken: settings.AdminAPIToken, AdminUsername: settings.AdminUsername, AdminPassword: settings.AdminPassword, SessionSecret: settings.SessionSecret})
	testServer := httptest.NewServer(httpapi.New(settings, service, control, slog.New(slog.NewTextHandler(io.Discard, nil))).Handler())
	defer testServer.Close()
	response, err := testServer.Client().Get(testServer.URL + "/v1/models")
	if err != nil {
		t.Fatalf("get models: %v", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", response.StatusCode)
	}
}

func TestCompatibilityAdaptersAndOpenAPI(t *testing.T) {
	server := newCompatibilityServer(t)
	defer server.Close()

	responses := apiPost(t, server, "/v1/responses", `{"model":"human","background":true,"input":"你好"}`, "test-api-key")
	if responses.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(responses.Body)
		t.Fatalf("responses status=%d body=%s", responses.StatusCode, body)
	}
	var responseBody map[string]any
	_ = json.NewDecoder(responses.Body).Decode(&responseBody)
	responses.Body.Close()
	if !strings.HasPrefix(responseBody["id"].(string), "resp_") || responseBody["status"] != "pending" {
		t.Fatalf("unexpected Responses body: %#v", responseBody)
	}

	claude := apiPost(t, server, "/v1/messages/count_tokens", `{"model":"claude-compatible","messages":[{"role":"user","content":"你好"}]}`, "test-api-key")
	if claude.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(claude.Body)
		t.Fatalf("claude count status=%d body=%s", claude.StatusCode, body)
	}
	claude.Body.Close()

	gemini := apiPost(t, server, "/v1beta/models/gemini-compatible:countTokens", `{"systemInstruction":{"parts":[{"text":"系统提示"}]},"contents":[{"role":"user","parts":[{"text":"你好"}]}]}`, "test-api-key")
	if gemini.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(gemini.Body)
		t.Fatalf("gemini count status=%d body=%s", gemini.StatusCode, body)
	}
	var geminiBody map[string]any
	_ = json.NewDecoder(gemini.Body).Decode(&geminiBody)
	gemini.Body.Close()
	if geminiBody["totalTokens"].(float64) < 1 {
		t.Fatalf("Gemini systemInstruction was not normalized: %#v", geminiBody)
	}

	conflict := apiPost(t, server, "/v1/responses", `{"model":"human","background":true,"input":"你好","previous_response_id":"resp_old","conversation":"conversation_1"}`, "test-api-key")
	if conflict.StatusCode != http.StatusBadRequest {
		body, _ := io.ReadAll(conflict.Body)
		t.Fatalf("expected previous/conversation conflict, got %d: %s", conflict.StatusCode, body)
	}
	conflict.Body.Close()

	openAPI, err := server.Client().Get(server.URL + "/openapi.json")
	if err != nil || openAPI.StatusCode != http.StatusOK {
		t.Fatalf("OpenAPI unavailable: status=%v err=%v", openAPI.StatusCode, err)
	}
	openAPI.Body.Close()
}

func TestAsyncResponsesAreIsolatedByAPIKey(t *testing.T) {
	server := newCompatibilityServer(t)
	defer server.Close()

	createdKey, _ := http.NewRequest(http.MethodPost, server.URL+"/admin/api/v1/api-keys", strings.NewReader(`{"name":"isolated client","rate_limit_per_minute":60,"daily_limit":100,"max_concurrent":5}`))
	createdKey.Header.Set("X-Admin-Token", "test-admin-token")
	createdKey.Header.Set("Content-Type", "application/json")
	keyResponse, err := server.Client().Do(createdKey)
	if err != nil || keyResponse.StatusCode != http.StatusCreated {
		t.Fatalf("create managed key: status=%v err=%v", keyResponse.StatusCode, err)
	}
	var keyBody map[string]any
	_ = json.NewDecoder(keyResponse.Body).Decode(&keyBody)
	keyResponse.Body.Close()
	managedKey, _ := keyBody["key"].(string)
	if managedKey == "" {
		t.Fatalf("create managed key omitted secret: %#v", keyBody)
	}

	created := apiPost(t, server, "/v1/responses", `{"model":"human","background":true,"input":"private"}`, "test-api-key")
	var createdBody map[string]any
	_ = json.NewDecoder(created.Body).Decode(&createdBody)
	created.Body.Close()
	id, _ := createdBody["id"].(string)
	if id == "" {
		t.Fatalf("master response omitted id: %#v", createdBody)
	}

	masterGet, _ := http.NewRequest(http.MethodGet, server.URL+"/v1/responses/"+id, nil)
	masterGet.Header.Set("Authorization", "Bearer test-api-key")
	masterResponse, err := server.Client().Do(masterGet)
	if err != nil || masterResponse.StatusCode != http.StatusOK {
		t.Fatalf("master cannot read own response: status=%v err=%v", masterResponse.StatusCode, err)
	}
	masterResponse.Body.Close()

	foreignGet, _ := http.NewRequest(http.MethodGet, server.URL+"/v1/responses/"+id, nil)
	foreignGet.Header.Set("Authorization", "Bearer "+managedKey)
	foreignResponse, err := server.Client().Do(foreignGet)
	if err != nil || foreignResponse.StatusCode != http.StatusNotFound {
		t.Fatalf("managed key crossed ownership boundary: status=%v err=%v", foreignResponse.StatusCode, err)
	}
	foreignResponse.Body.Close()
}

func TestAdminDevicePairingAndRefresh(t *testing.T) {
	server := newCompatibilityServer(t)
	defer server.Close()
	create, _ := http.NewRequest(http.MethodPost, server.URL+"/admin/api/v1/pairing-codes", strings.NewReader(`{"label":"test phone"}`))
	create.Header.Set("X-Admin-Token", "test-admin-token")
	create.Header.Set("Content-Type", "application/json")
	created, err := server.Client().Do(create)
	if err != nil || created.StatusCode != http.StatusCreated {
		t.Fatalf("create pairing code: status=%v err=%v", created.StatusCode, err)
	}
	var pairing map[string]any
	_ = json.NewDecoder(created.Body).Decode(&pairing)
	created.Body.Close()
	pairingURL, err := url.Parse(pairing["pairing_uri"].(string))
	if err != nil || pairingURL.Scheme != "iamllm" || pairingURL.Host != "pair" {
		t.Fatalf("invalid pairing uri: %v err=%v", pairing["pairing_uri"], err)
	}
	if pairingURL.Query().Get("server") != server.URL || pairingURL.Query().Get("code") != pairing["code"] {
		t.Fatalf("pairing uri does not match response: %v", pairingURL)
	}
	pair := apiPost(t, server, "/admin/api/v1/auth/pair", `{"code":"`+pairing["code"].(string)+`","device_name":"测试手机","platform":"android","device_model":"Pixel 9","os_version":"Android 16","app_version":"0.1.0+1","locale":"zh-CN","timezone":"Asia/Shanghai"}`, "")
	if pair.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(pair.Body)
		t.Fatalf("pair device status=%d body=%s", pair.StatusCode, body)
	}
	var tokens map[string]any
	_ = json.NewDecoder(pair.Body).Decode(&tokens)
	pair.Body.Close()
	access := tokens["access_token"].(string)
	profile, _ := http.NewRequest(http.MethodGet, server.URL+"/admin/api/v1/profile", nil)
	profile.Header.Set("Authorization", "Bearer "+access)
	profileResponse, err := server.Client().Do(profile)
	if err != nil || profileResponse.StatusCode != http.StatusOK {
		t.Fatalf("paired access token failed: status=%v err=%v", profileResponse.StatusCode, err)
	}
	profileResponse.Body.Close()

	devicesRequest, _ := http.NewRequest(http.MethodGet, server.URL+"/admin/api/v1/devices", nil)
	devicesRequest.Header.Set("Authorization", "Bearer "+access)
	devicesResponse, err := server.Client().Do(devicesRequest)
	if err != nil || devicesResponse.StatusCode != http.StatusOK {
		t.Fatalf("list devices: status=%v err=%v", devicesResponse.StatusCode, err)
	}
	var deviceList struct {
		CurrentDeviceID string `json:"current_device_id"`
		Items           []struct {
			ID          string `json:"id"`
			Name        string `json:"name"`
			DeviceModel string `json:"device_model"`
			OSVersion   string `json:"os_version"`
			AppVersion  string `json:"app_version"`
			Locale      string `json:"locale"`
			Timezone    string `json:"timezone"`
			IPAddress   string `json:"ip_address"`
			LastSeenAt  int64  `json:"last_seen_at"`
		} `json:"items"`
	}
	_ = json.NewDecoder(devicesResponse.Body).Decode(&deviceList)
	devicesResponse.Body.Close()
	if len(deviceList.Items) != 1 || deviceList.CurrentDeviceID != deviceList.Items[0].ID {
		t.Fatalf("current device was not identified: %#v", deviceList)
	}
	device := deviceList.Items[0]
	if device.Name != "测试手机" || device.DeviceModel != "Pixel 9" || device.OSVersion != "Android 16" || device.AppVersion != "0.1.0+1" || device.Locale != "zh-CN" || device.Timezone != "Asia/Shanghai" || device.IPAddress == "" || device.LastSeenAt == 0 {
		t.Fatalf("device metadata was not persisted: %#v", device)
	}

	replay := apiPost(t, server, "/admin/api/v1/auth/pair", `{"code":"`+pairing["code"].(string)+`","device_name":"Again","platform":"flutter"}`, "")
	if replay.StatusCode != http.StatusUnauthorized {
		t.Fatalf("pairing code should be one-time, got %d", replay.StatusCode)
	}
	replay.Body.Close()
}

func TestConversationStateSyncsAcrossPairedAdminDevices(t *testing.T) {
	server := newCompatibilityServer(t)
	defer server.Close()
	phoneToken := pairAdminDevice(t, server, "iPhone")
	browserToken := pairAdminDevice(t, server, "Safari")

	created := apiPost(t, server, "/v1/responses", `{"model":"human","background":true,"input":"跨设备测试"}`, "test-api-key")
	if created.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(created.Body)
		created.Body.Close()
		t.Fatalf("create background response status=%d body=%s", created.StatusCode, body)
	}
	var createdBody map[string]any
	if err := json.NewDecoder(created.Body).Decode(&createdBody); err != nil {
		t.Fatal(err)
	}
	created.Body.Close()
	requestID, _ := createdBody["id"].(string)
	if requestID == "" {
		t.Fatalf("background response omitted id: %#v", createdBody)
	}

	drafted := adminJSONWithToken(t, server, http.MethodPut, "/admin/api/v1/requests/"+requestID+"/draft", `{"content":"我在手机上写到一半"}`, phoneToken, http.StatusOK)
	if drafted["draft"] != "我在手机上写到一半" || drafted["draft_device_id"] == "" || drafted["draft_updated_at"].(float64) <= 0 {
		t.Fatalf("phone draft was not persisted: %#v", drafted)
	}
	phoneDeviceID := drafted["draft_device_id"]

	browserDetail := adminJSONWithToken(t, server, http.MethodGet, "/admin/api/v1/requests/"+requestID, "", browserToken, http.StatusOK)
	if browserDetail["draft"] != "我在手机上写到一半" || browserDetail["draft_device_id"] != phoneDeviceID {
		t.Fatalf("browser did not see phone draft: %#v", browserDetail)
	}
	read := adminJSONWithToken(t, server, http.MethodPut, "/admin/api/v1/requests/"+requestID+"/read", "", browserToken, http.StatusOK)
	if read["read_at"].(float64) <= 0 {
		t.Fatalf("browser read state was not persisted: %#v", read)
	}

	phoneList := adminJSONWithToken(t, server, http.MethodGet, "/admin/api/v1/requests?status=pending", "", phoneToken, http.StatusOK)
	items, _ := phoneList["items"].([]any)
	listed := findRequest(t, items, requestID)
	if listed["read_at"].(float64) <= 0 || listed["draft"] != "我在手机上写到一半" {
		t.Fatalf("phone list did not receive shared state: %#v", listed)
	}

	chunk := adminJSONWithToken(t, server, http.MethodPost, "/admin/api/v1/requests/"+requestID+"/chunks", `{"chunk_id":"phone-1","content":"收到，"}`, phoneToken, http.StatusCreated)
	chunkItem, _ := chunk["chunk"].(map[string]any)
	if chunkItem["content"] != "收到，" {
		t.Fatalf("unexpected chunk response: %#v", chunk)
	}
	afterChunk := adminJSONWithToken(t, server, http.MethodGet, "/admin/api/v1/requests/"+requestID, "", browserToken, http.StatusOK)
	if afterChunk["draft"] != "" || afterChunk["draft_device_id"] != "" || afterChunk["draft_updated_at"].(float64) != 0 {
		t.Fatalf("successful chunk did not clear the shared draft: %#v", afterChunk)
	}
	chunks, _ := afterChunk["stream_chunks"].([]any)
	if len(chunks) != 1 || chunks[0].(map[string]any)["content"] != "收到，" {
		t.Fatalf("browser did not see phone chunk: %#v", chunks)
	}

	completed := adminJSONWithToken(t, server, http.MethodPost, "/admin/api/v1/requests/"+requestID+"/complete", `{}`, browserToken, http.StatusOK)
	if completed["status"] != "answered" || completed["answer"] != "收到，" {
		t.Fatalf("browser could not complete phone reply: %#v", completed)
	}
	phoneDetail := adminJSONWithToken(t, server, http.MethodGet, "/admin/api/v1/requests/"+requestID, "", phoneToken, http.StatusOK)
	if phoneDetail["status"] != "answered" || phoneDetail["answer"] != "收到，" {
		t.Fatalf("phone did not receive browser completion: %#v", phoneDetail)
	}
}

func pairAdminDevice(t *testing.T, server *httptest.Server, name string) string {
	t.Helper()
	create, _ := http.NewRequest(http.MethodPost, server.URL+"/admin/api/v1/pairing-codes", strings.NewReader(`{"label":"`+name+`"}`))
	create.Header.Set("X-Admin-Token", "test-admin-token")
	create.Header.Set("Content-Type", "application/json")
	created, err := server.Client().Do(create)
	if err != nil || created.StatusCode != http.StatusCreated {
		t.Fatalf("create pairing for %s: status=%v err=%v", name, created.StatusCode, err)
	}
	var pairing map[string]any
	if err := json.NewDecoder(created.Body).Decode(&pairing); err != nil {
		t.Fatal(err)
	}
	created.Body.Close()
	payload, _ := json.Marshal(map[string]string{"code": pairing["code"].(string), "device_name": name, "platform": "test"})
	paired := apiPost(t, server, "/admin/api/v1/auth/pair", string(payload), "")
	if paired.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(paired.Body)
		paired.Body.Close()
		t.Fatalf("pair %s status=%d body=%s", name, paired.StatusCode, body)
	}
	var tokens map[string]any
	if err := json.NewDecoder(paired.Body).Decode(&tokens); err != nil {
		t.Fatal(err)
	}
	paired.Body.Close()
	access, _ := tokens["access_token"].(string)
	if access == "" {
		t.Fatalf("pair %s omitted access token: %#v", name, tokens)
	}
	return access
}

func adminJSONWithToken(t *testing.T, server *httptest.Server, method, path, body, token string, expectedStatus int) map[string]any {
	t.Helper()
	request, _ := http.NewRequest(method, server.URL+path, strings.NewReader(body))
	request.Header.Set("Authorization", "Bearer "+token)
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := server.Client().Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer response.Body.Close()
	if response.StatusCode != expectedStatus {
		payload, _ := io.ReadAll(response.Body)
		t.Fatalf("%s %s status=%d want=%d body=%s", method, path, response.StatusCode, expectedStatus, payload)
	}
	var result map[string]any
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		t.Fatalf("decode %s %s: %v", method, path, err)
	}
	return result
}

func findRequest(t *testing.T, items []any, requestID string) map[string]any {
	t.Helper()
	for _, raw := range items {
		item, _ := raw.(map[string]any)
		if item["id"] == requestID {
			return item
		}
	}
	t.Fatalf("request %s not found in %#v", requestID, items)
	return nil
}

func newCompatibilityServer(t *testing.T) *httptest.Server {
	t.Helper()
	store, err := sqlite.Open(context.Background(), filepath.Join(t.TempDir(), "iamllm.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	settings := config.Config{
		Environment: "test", APIKey: "test-api-key", AdminAPIToken: "test-admin-token",
		ModelName: "human", SessionSecret: "test-session-secret", AdminUsername: "admin",
		AdminPassword: "test-password", JobTTL: time.Hour, ResponseTimeout: 3 * time.Second,
		PollInterval: 5 * time.Millisecond, StreamIdle: time.Minute, TimeoutFallbacks: []string{"timeout"},
	}
	service := application.New(store, application.Options{JobTTL: settings.JobTTL, ResponseTimeout: settings.ResponseTimeout, PollInterval: settings.PollInterval, StreamIdle: settings.StreamIdle, TimeoutFallbacks: settings.TimeoutFallbacks})
	control := application.NewControl(store, application.ControlOptions{MasterAPIKey: settings.APIKey, AdminToken: settings.AdminAPIToken, AdminUsername: settings.AdminUsername, AdminPassword: settings.AdminPassword, SessionSecret: settings.SessionSecret})
	return httptest.NewServer(httpapi.New(settings, service, control, slog.New(slog.NewTextHandler(io.Discard, nil))).Handler())
}

func apiPost(t *testing.T, server *httptest.Server, path, body, apiKey string) *http.Response {
	t.Helper()
	request, _ := http.NewRequest(http.MethodPost, server.URL+path, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		request.Header.Set("Authorization", "Bearer "+apiKey)
	}
	response, err := server.Client().Do(request)
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	return response
}

func appendChunk(t *testing.T, server *httptest.Server, requestID, chunkID, content string, expectedStatus int) {
	t.Helper()
	payload, _ := json.Marshal(map[string]string{"chunk_id": chunkID, "content": content})
	adminPost(t, server, "/admin/api/v1/requests/"+requestID+"/chunks", string(payload), expectedStatus)
}

func adminPost(t *testing.T, server *httptest.Server, path, payload string, expectedStatus int) {
	t.Helper()
	request, _ := http.NewRequest(http.MethodPost, server.URL+path, bytes.NewBufferString(payload))
	request.Header.Set("X-Admin-Token", "test-admin-token")
	request.Header.Set("Content-Type", "application/json")
	response, err := server.Client().Do(request)
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	defer response.Body.Close()
	if response.StatusCode != expectedStatus {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("POST %s status=%d want=%d body=%s", path, response.StatusCode, expectedStatus, body)
	}
}
