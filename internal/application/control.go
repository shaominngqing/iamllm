package application

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

var (
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrInvalidToken       = errors.New("invalid or expired token")
	ErrInvalidPairingCode = errors.New("invalid or expired pairing code")
)

type ControlOptions struct {
	MasterAPIKey, AdminToken, AdminUsername, AdminPassword, SessionSecret string
	Timezone                                                              *time.Location
}

type ControlService struct {
	repository repository.Repository
	options    ControlOptions
}

func NewControl(repository repository.Repository, options ControlOptions) *ControlService {
	return &ControlService{repository: repository, options: options}
}

type APIPrincipal struct {
	ID, Name string
	Managed  bool
}
type LimitError struct {
	Reason     string
	RetryAfter int
}

func (err LimitError) Error() string {
	return map[string]string{"minute": "每分钟调用额度已用完，请稍后再试。", "daily": "今天的调用额度已经用完。", "concurrent": "已有太多问题在等待回答。"}[err.Reason]
}

func (service *ControlService) AuthenticateAPIKey(ctx context.Context, secret string, count bool) (APIPrincipal, error) {
	if secureEqual(secret, service.options.MasterAPIKey) {
		return APIPrincipal{ID: "master", Name: "环境变量总钥匙"}, nil
	}
	minuteStart, dayStart := service.usageWindows()
	result, err := service.repository.AuthorizeAPIKey(ctx, service.digest(secret), count, minuteStart, dayStart)
	if err != nil {
		return APIPrincipal{}, err
	}
	if result.Key == nil {
		return APIPrincipal{}, ErrInvalidCredentials
	}
	if result.LimitReason != "" {
		return APIPrincipal{}, LimitError{result.LimitReason, result.RetryAfter}
	}
	return APIPrincipal{ID: result.Key.ID, Name: result.Key.Name, Managed: true}, nil
}

func (service *ControlService) CreateAPIKey(ctx context.Context, name string, minute, daily, concurrent int) (string, domain.APIKey, error) {
	secret, err := randomToken("sk", 32)
	if err != nil {
		return "", domain.APIKey{}, err
	}
	id, err := domain.NewID("key")
	if err != nil {
		return "", domain.APIKey{}, err
	}
	now := time.Now().UnixMilli()
	item := domain.APIKey{ID: id, Name: strings.TrimSpace(name), KeyHint: keyHint(secret), Active: true, RateLimitPerMinute: minute, DailyLimit: daily, MaxConcurrent: concurrent, CreatedAt: now, UpdatedAt: now}
	item, err = service.repository.CreateAPIKey(ctx, item, service.digest(secret))
	return secret, item, err
}
func (service *ControlService) ListAPIKeys(ctx context.Context) ([]domain.APIKey, error) {
	a, b := service.usageWindows()
	return service.repository.ListAPIKeys(ctx, a, b)
}
func (service *ControlService) GetAPIKey(ctx context.Context, id string) (domain.APIKey, error) {
	a, b := service.usageWindows()
	return service.repository.GetAPIKey(ctx, id, a, b)
}
func (service *ControlService) SaveAPIKey(ctx context.Context, item domain.APIKey) (domain.APIKey, error) {
	return service.repository.SaveAPIKey(ctx, item)
}
func (service *ControlService) RevokeAPIKey(ctx context.Context, id string) (domain.APIKey, error) {
	return service.repository.RevokeAPIKey(ctx, id)
}

func (service *ControlService) Profile(ctx context.Context) (domain.Profile, error) {
	return service.repository.GetProfile(ctx)
}
func (service *ControlService) SaveProfile(ctx context.Context, item domain.Profile) (domain.Profile, error) {
	return service.repository.UpdateProfile(ctx, item)
}
func (service *ControlService) QuickReplies(ctx context.Context, all bool) ([]domain.QuickReply, error) {
	return service.repository.ListQuickReplies(ctx, all)
}
func (service *ControlService) QuickReply(ctx context.Context, id string) (domain.QuickReply, error) {
	return service.repository.GetQuickReply(ctx, id)
}
func (service *ControlService) SaveQuickReply(ctx context.Context, item domain.QuickReply) (domain.QuickReply, error) {
	return service.repository.SaveQuickReply(ctx, item)
}
func (service *ControlService) DeleteQuickReply(ctx context.Context, id string) error {
	return service.repository.DeleteQuickReply(ctx, id)
}
func (service *ControlService) AutoRules(ctx context.Context) ([]domain.AutoReplyRule, error) {
	return service.repository.ListAutoReplyRules(ctx)
}
func (service *ControlService) AutoRule(ctx context.Context, id string) (domain.AutoReplyRule, error) {
	return service.repository.GetAutoReplyRule(ctx, id)
}
func (service *ControlService) SaveAutoRule(ctx context.Context, item domain.AutoReplyRule) (domain.AutoReplyRule, error) {
	return service.repository.SaveAutoReplyRule(ctx, item)
}
func (service *ControlService) DeleteAutoRule(ctx context.Context, id string) error {
	return service.repository.DeleteAutoReplyRule(ctx, id)
}
func (service *ControlService) PreviewAutoRule(ctx context.Context, text string) (*domain.AutoReplyRule, error) {
	now := time.Now().In(service.location())
	return service.repository.ResolveAutoReply(ctx, text, now.Format("15:04"), (int(now.Weekday())+6)%7)
}

type TokenPair struct {
	AccessToken  string             `json:"access_token"`
	RefreshToken string             `json:"refresh_token"`
	ExpiresIn    int                `json:"expires_in"`
	Device       domain.AdminDevice `json:"device"`
}
type accessClaims struct {
	DeviceID  string `json:"device_id"`
	ExpiresAt int64  `json:"exp"`
}

func (service *ControlService) Login(ctx context.Context, username, password string, device domain.AdminDevice) (TokenPair, error) {
	if !secureEqual(username, service.options.AdminUsername) || !secureEqual(password, service.options.AdminPassword) {
		return TokenPair{}, ErrInvalidCredentials
	}
	return service.createDevice(ctx, device)
}
func (service *ControlService) CreatePairing(ctx context.Context, label string) (string, int64, error) {
	code, err := numericCode(8)
	if err != nil {
		return "", 0, err
	}
	expires := time.Now().Add(10 * time.Minute).UnixMilli()
	err = service.repository.SavePairingCode(ctx, service.digest("pair:"+code), label, expires)
	return code, expires, err
}
func (service *ControlService) Pair(ctx context.Context, code string, device domain.AdminDevice) (TokenPair, error) {
	ok, err := service.repository.ConsumePairingCode(ctx, service.digest("pair:"+strings.TrimSpace(code)), time.Now().UnixMilli())
	if err != nil {
		return TokenPair{}, err
	}
	if !ok {
		return TokenPair{}, ErrInvalidPairingCode
	}
	return service.createDevice(ctx, device)
}
func (service *ControlService) Refresh(ctx context.Context, refresh string, metadata domain.AdminDevice) (TokenPair, error) {
	hash := service.digest("refresh:" + refresh)
	device, err := service.repository.GetDeviceByRefreshHash(ctx, hash)
	if err != nil {
		return TokenPair{}, ErrInvalidToken
	}
	newRefresh, err := randomToken("rt", 32)
	if err != nil {
		return TokenPair{}, err
	}
	if err := service.repository.RotateDeviceRefresh(ctx, device.ID, service.digest("refresh:"+newRefresh)); err != nil {
		return TokenPair{}, err
	}
	if err := service.repository.UpdateDeviceMetadata(ctx, device.ID, metadata); err != nil {
		return TokenPair{}, err
	}
	mergeDeviceMetadata(&device, metadata)
	device.LastSeenAt, device.UpdatedAt = time.Now().UnixMilli(), time.Now().UnixMilli()
	access, err := service.signAccess(device.ID, time.Now().Add(15*time.Minute))
	if err != nil {
		return TokenPair{}, err
	}
	return TokenPair{access, newRefresh, 900, device}, nil
}
func (service *ControlService) ValidateAccess(token string) (string, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return "", ErrInvalidToken
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return "", ErrInvalidToken
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", ErrInvalidToken
	}
	expected := service.mac(payload)
	if subtle.ConstantTimeCompare(signature, expected) != 1 {
		return "", ErrInvalidToken
	}
	var claims accessClaims
	if json.Unmarshal(payload, &claims) != nil || claims.DeviceID == "" || claims.ExpiresAt < time.Now().Unix() {
		return "", ErrInvalidToken
	}
	return claims.DeviceID, nil
}
func (service *ControlService) IsMasterAdmin(token string) bool {
	return secureEqual(token, service.options.AdminToken)
}
func (service *ControlService) Devices(ctx context.Context) ([]domain.AdminDevice, error) {
	return service.repository.ListDevices(ctx)
}
func (service *ControlService) RevokeDevice(ctx context.Context, id string) error {
	return service.repository.RevokeDevice(ctx, id)
}

func (service *ControlService) UpdateDeviceMetadata(ctx context.Context, id string, item domain.AdminDevice) error {
	return service.repository.UpdateDeviceMetadata(ctx, id, item)
}

func (service *ControlService) TouchDevice(ctx context.Context, id, ipAddress, userAgent string) error {
	return service.repository.TouchDevice(ctx, id, ipAddress, userAgent)
}

func (service *ControlService) createDevice(ctx context.Context, device domain.AdminDevice) (TokenPair, error) {
	id, err := domain.NewID("device")
	if err != nil {
		return TokenPair{}, err
	}
	refresh, err := randomToken("rt", 32)
	if err != nil {
		return TokenPair{}, err
	}
	now := time.Now().UnixMilli()
	if strings.TrimSpace(device.Name) == "" {
		device.Name = "管理设备"
	}
	if strings.TrimSpace(device.Platform) == "" {
		device.Platform = "unknown"
	}
	device.ID, device.Name, device.Platform = id, strings.TrimSpace(device.Name), strings.TrimSpace(device.Platform)
	device.CreatedAt, device.UpdatedAt, device.LastSeenAt = now, now, now
	device, err = service.repository.CreateDevice(ctx, device, service.digest("refresh:"+refresh))
	if err != nil {
		return TokenPair{}, err
	}
	access, err := service.signAccess(id, time.Now().Add(15*time.Minute))
	if err != nil {
		return TokenPair{}, err
	}
	return TokenPair{access, refresh, 900, device}, nil
}

func mergeDeviceMetadata(target *domain.AdminDevice, source domain.AdminDevice) {
	if source.Name != "" {
		target.Name = source.Name
	}
	if source.Platform != "" {
		target.Platform = source.Platform
	}
	if source.DeviceModel != "" {
		target.DeviceModel = source.DeviceModel
	}
	if source.OSVersion != "" {
		target.OSVersion = source.OSVersion
	}
	if source.AppVersion != "" {
		target.AppVersion = source.AppVersion
	}
	if source.Locale != "" {
		target.Locale = source.Locale
	}
	if source.Timezone != "" {
		target.Timezone = source.Timezone
	}
	if source.IPAddress != "" {
		target.IPAddress = source.IPAddress
	}
	if source.UserAgent != "" {
		target.UserAgent = source.UserAgent
	}
}
func (service *ControlService) signAccess(deviceID string, expires time.Time) (string, error) {
	payload, err := json.Marshal(accessClaims{deviceID, expires.Unix()})
	if err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(service.mac(payload)), nil
}
func (service *ControlService) mac(value []byte) []byte {
	hash := hmac.New(sha256.New, []byte(service.options.SessionSecret))
	_, _ = hash.Write(value)
	return hash.Sum(nil)
}
func (service *ControlService) digest(value string) string {
	return hex.EncodeToString(service.mac([]byte(value)))
}
func (service *ControlService) usageWindows() (int64, int64) {
	now := time.Now().In(service.location())
	minute := now.Truncate(time.Minute)
	day := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, service.location())
	return minute.UnixMilli(), day.UnixMilli()
}
func (service *ControlService) location() *time.Location {
	if service.options.Timezone != nil {
		return service.options.Timezone
	}
	return time.Local
}
func secureEqual(a, b string) bool {
	if len(a) != len(b) || len(a) == 0 {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}
func randomToken(prefix string, size int) (string, error) {
	buffer := make([]byte, size)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return prefix + "-" + base64.RawURLEncoding.EncodeToString(buffer), nil
}
func numericCode(size int) (string, error) {
	buffer := make([]byte, size)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	for i := range buffer {
		buffer[i] = '0' + buffer[i]%10
	}
	return string(buffer), nil
}
func keyHint(value string) string {
	if len(value) < 14 {
		return value
	}
	return value[:9] + "…" + value[len(value)-4:]
}
func (err LimitError) Unwrap() error { return fmt.Errorf("rate limited: %s", err.Reason) }
