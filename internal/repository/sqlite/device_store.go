package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

func (store *Store) SavePairingCode(ctx context.Context, codeHash, label string, expiresAt int64) error {
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO pairing_codes(code_hash, label, expires_at, created_at, used_at)
		VALUES (?, ?, ?, ?, NULL)
		ON CONFLICT(code_hash) DO UPDATE SET label=excluded.label, expires_at=excluded.expires_at,
		created_at=excluded.created_at, used_at=NULL
	`, codeHash, label, expiresAt, time.Now().UnixMilli())
	return err
}

func (store *Store) ConsumePairingCode(ctx context.Context, codeHash string, now int64) (bool, error) {
	result, err := store.database.ExecContext(ctx, `
		UPDATE pairing_codes SET used_at = ?
		WHERE code_hash = ? AND used_at IS NULL AND expires_at >= ?
	`, now, codeHash, now)
	if err != nil {
		return false, err
	}
	affected, _ := result.RowsAffected()
	return affected == 1, nil
}

func scanDevice(row scanner) (domain.AdminDevice, error) {
	var item domain.AdminDevice
	var model, osVersion, appVersion, locale, timezone, ipAddress, userAgent sql.NullString
	var lastSeen, revoked sql.NullInt64
	err := row.Scan(&item.ID, &item.Name, &item.Platform, &model, &osVersion, &appVersion,
		&locale, &timezone, &ipAddress, &userAgent, &item.CreatedAt,
		&item.UpdatedAt, &lastSeen, &revoked)
	item.DeviceModel, item.OSVersion, item.AppVersion = model.String, osVersion.String, appVersion.String
	item.Locale, item.Timezone, item.IPAddress, item.UserAgent = locale.String, timezone.String, ipAddress.String, userAgent.String
	item.LastSeenAt, item.RevokedAt = lastSeen.Int64, revoked.Int64
	return item, err
}

const deviceColumns = `id, name, platform, device_model, os_version, app_version, locale, timezone, ip_address, user_agent, created_at, updated_at, last_seen_at, revoked_at`

func (store *Store) CreateDevice(ctx context.Context, item domain.AdminDevice, refreshHash string) (domain.AdminDevice, error) {
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO admin_devices(id, name, platform, refresh_hash, device_model, os_version,
			app_version, locale, timezone, ip_address, user_agent, created_at, updated_at, last_seen_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, item.ID, item.Name, item.Platform, refreshHash, nullString(item.DeviceModel), nullString(item.OSVersion),
		nullString(item.AppVersion), nullString(item.Locale), nullString(item.Timezone), nullString(item.IPAddress),
		nullString(item.UserAgent), item.CreatedAt, item.UpdatedAt, item.LastSeenAt)
	if err != nil {
		return item, fmt.Errorf("create device: %w", err)
	}
	return item, nil
}

func (store *Store) GetDeviceByRefreshHash(ctx context.Context, refreshHash string) (domain.AdminDevice, error) {
	item, err := scanDevice(store.database.QueryRowContext(ctx, `SELECT `+deviceColumns+` FROM admin_devices WHERE refresh_hash = ? AND revoked_at IS NULL`, refreshHash))
	if errors.Is(err, sql.ErrNoRows) {
		return item, repository.ErrNotFound
	}
	return item, err
}

func (store *Store) RotateDeviceRefresh(ctx context.Context, id, refreshHash string) error {
	now := time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `UPDATE admin_devices SET refresh_hash=?, updated_at=?, last_seen_at=? WHERE id=? AND revoked_at IS NULL`, refreshHash, now, now, id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return repository.ErrNotFound
	}
	return nil
}

func (store *Store) ListDevices(ctx context.Context) ([]domain.AdminDevice, error) {
	rows, err := store.database.QueryContext(ctx, `SELECT `+deviceColumns+` FROM admin_devices ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.AdminDevice{}
	for rows.Next() {
		item, err := scanDevice(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) UpdateDeviceMetadata(ctx context.Context, id string, item domain.AdminDevice) error {
	now := time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `
		UPDATE admin_devices SET
			name=COALESCE(NULLIF(?, ''), name), platform=COALESCE(NULLIF(?, ''), platform),
			device_model=COALESCE(NULLIF(?, ''), device_model), os_version=COALESCE(NULLIF(?, ''), os_version),
			app_version=COALESCE(NULLIF(?, ''), app_version), locale=COALESCE(NULLIF(?, ''), locale),
			timezone=COALESCE(NULLIF(?, ''), timezone), ip_address=COALESCE(NULLIF(?, ''), ip_address),
			user_agent=COALESCE(NULLIF(?, ''), user_agent), updated_at=?, last_seen_at=?
		WHERE id=? AND revoked_at IS NULL
	`, item.Name, item.Platform, item.DeviceModel, item.OSVersion, item.AppVersion, item.Locale,
		item.Timezone, item.IPAddress, item.UserAgent, now, now, id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return repository.ErrNotFound
	}
	return nil
}

func (store *Store) TouchDevice(ctx context.Context, id, ipAddress, userAgent string) error {
	now := time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `
		UPDATE admin_devices SET last_seen_at=?, ip_address=COALESCE(NULLIF(?, ''), ip_address),
			user_agent=COALESCE(NULLIF(?, ''), user_agent), updated_at=?
		WHERE id=? AND revoked_at IS NULL AND (
			last_seen_at IS NULL OR last_seen_at < ? OR
			COALESCE(ip_address, '') <> ? OR COALESCE(user_agent, '') <> ?
		)
	`, now, ipAddress, userAgent, now, id, now-30_000, ipAddress, userAgent)
	if err != nil {
		return err
	}
	_, _ = result.RowsAffected()
	return nil
}

func (store *Store) RevokeDevice(ctx context.Context, id string) error {
	now := time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `UPDATE admin_devices SET revoked_at=?, updated_at=? WHERE id=? AND revoked_at IS NULL`, now, now, id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return repository.ErrNotFound
	}
	return nil
}

func (store *Store) CreateConversation(ctx context.Context, item domain.Conversation, ownerHash string) (domain.Conversation, error) {
	_, err := store.database.ExecContext(ctx, `INSERT INTO conversations(id, owner_hash, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)`, item.ID, ownerHash, item.Title, item.CreatedAt, item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("create conversation: %w", err)
	}
	item.Messages = []domain.Message{}
	return item, nil
}

func (store *Store) GetConversation(ctx context.Context, id, ownerHash string) (domain.Conversation, error) {
	var item domain.Conversation
	err := store.database.QueryRowContext(ctx, `SELECT id, title, created_at, updated_at FROM conversations WHERE id=? AND owner_hash=?`, id, ownerHash).Scan(&item.ID, &item.Title, &item.CreatedAt, &item.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return item, repository.ErrNotFound
	}
	if err != nil {
		return item, err
	}
	item.Messages, err = store.ConversationMessages(ctx, id)
	return item, err
}

func (store *Store) AddConversationMessage(ctx context.Context, conversationID string, message domain.Message, requestID string) error {
	if message.ID == "" {
		var err error
		message.ID, err = domain.NewID("msg")
		if err != nil {
			return err
		}
	}
	content := "null"
	if len(message.Content) > 0 {
		content = string(message.Content)
	}
	toolCalls := "null"
	if len(message.ToolCalls) > 0 {
		toolCalls = string(message.ToolCalls)
	}
	now := time.Now().UnixMilli()
	tx, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	_, err = tx.ExecContext(ctx, `
		INSERT INTO conversation_messages(id, conversation_id, role, content_json, tool_call_id, tool_calls_json, request_id, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)
	`, message.ID, conversationID, message.Role, content, nullString(message.ToolCallID), toolCalls, nullString(requestID), now)
	if err != nil {
		return fmt.Errorf("add conversation message: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE conversations SET updated_at=? WHERE id=?`, now, conversationID); err != nil {
		return err
	}
	return tx.Commit()
}

func (store *Store) ConversationMessages(ctx context.Context, conversationID string) ([]domain.Message, error) {
	rows, err := store.database.QueryContext(ctx, `
		SELECT id, role, content_json, COALESCE(tool_call_id,''), tool_calls_json
		FROM conversation_messages WHERE conversation_id=? ORDER BY created_at, id
	`, conversationID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.Message{}
	for rows.Next() {
		var item domain.Message
		var content, toolCalls sql.NullString
		if err := rows.Scan(&item.ID, &item.Role, &content, &item.ToolCallID, &toolCalls); err != nil {
			return nil, err
		}
		if content.Valid {
			item.Content = json.RawMessage(content.String)
		}
		if toolCalls.Valid && toolCalls.String != "null" {
			item.ToolCalls = json.RawMessage(toolCalls.String)
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) ConversationHasPending(ctx context.Context, conversationID string) (bool, error) {
	var count int
	err := store.database.QueryRowContext(ctx, `SELECT COUNT(*) FROM human_requests WHERE conversation_id=? AND status='pending'`, conversationID).Scan(&count)
	return count > 0, err
}

func (store *Store) RenameConversation(ctx context.Context, id, title string) error {
	title = strings.TrimSpace(title)
	runes := []rune(title)
	if len(runes) > 50 {
		title = string(runes[:49]) + "…"
	}
	_, err := store.database.ExecContext(ctx, `UPDATE conversations SET title=?, updated_at=? WHERE id=?`, title, time.Now().UnixMilli(), id)
	return err
}
