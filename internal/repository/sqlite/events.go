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

func (store *Store) insertEvent(
	ctx context.Context,
	exec executor,
	eventType string,
	resourceID string,
	payload map[string]any,
) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode admin event: %w", err)
	}
	_, err = exec.ExecContext(ctx, `
		INSERT INTO admin_events(event_type, resource_id, payload_json, created_at)
		VALUES (?, ?, ?, ?)
	`, eventType, nullString(resourceID), string(encoded), time.Now().UnixMilli())
	if err != nil {
		return fmt.Errorf("insert admin event: %w", err)
	}
	return nil
}

func (store *Store) ListEvents(ctx context.Context, afterID int64, limit int) ([]domain.AdminEvent, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	rows, err := store.database.QueryContext(ctx, `
		SELECT id, event_type, COALESCE(resource_id, ''), payload_json, created_at
		FROM admin_events WHERE id > ? ORDER BY id LIMIT ?
	`, afterID, limit)
	if err != nil {
		return nil, fmt.Errorf("list admin events: %w", err)
	}
	defer rows.Close()
	items := make([]domain.AdminEvent, 0)
	for rows.Next() {
		var item domain.AdminEvent
		var payload string
		if err := rows.Scan(&item.ID, &item.Type, &item.ResourceID, &payload, &item.CreatedAt); err != nil {
			return nil, fmt.Errorf("scan admin event: %w", err)
		}
		if err := json.Unmarshal([]byte(payload), &item.Payload); err != nil {
			return nil, fmt.Errorf("decode admin event: %w", err)
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) ClaimRequest(
	ctx context.Context,
	requestID string,
	ownerID string,
	ttl time.Duration,
) (domain.HumanRequest, error) {
	if ownerID == "" {
		return domain.HumanRequest{}, errors.New("operator id is required")
	}
	now := time.Now()
	result, err := store.database.ExecContext(ctx, `
		UPDATE human_requests
		SET claim_owner = ?, claim_expires_at = ?, updated_at = ?
		WHERE id = ? AND status = 'pending'
		  AND (claim_owner IS NULL OR claim_owner = ? OR claim_expires_at < ?)
	`, ownerID, now.Add(ttl).UnixMilli(), now.UnixMilli(), requestID, ownerID, now.UnixMilli())
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("claim request: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		var status string
		var current sql.NullString
		err := store.database.QueryRowContext(ctx, "SELECT status, claim_owner FROM human_requests WHERE id = ?", requestID).Scan(&status, &current)
		if errors.Is(err, sql.ErrNoRows) {
			return domain.HumanRequest{}, repository.ErrNotFound
		}
		if status != "pending" {
			return domain.HumanRequest{}, repository.ErrNotPending
		}
		return domain.HumanRequest{}, repository.ErrClaimed
	}
	_, _ = store.database.ExecContext(ctx, `
		INSERT INTO admin_events(event_type, resource_id, payload_json, created_at)
		VALUES ('request.claimed', ?, json_object('operator_id', ?), ?)
	`, requestID, ownerID, now.UnixMilli())
	return store.GetRequest(ctx, requestID)
}

func (store *Store) ReleaseClaim(ctx context.Context, requestID string, ownerID string) error {
	result, err := store.database.ExecContext(ctx, `
		UPDATE human_requests SET claim_owner = NULL, claim_expires_at = NULL
		WHERE id = ? AND claim_owner = ?
	`, requestID, ownerID)
	if err != nil {
		return fmt.Errorf("release request claim: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		return repository.ErrClaimed
	}
	return nil
}

func (store *Store) MarkRequestRead(ctx context.Context, requestID string) (domain.HumanRequest, error) {
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("begin mark request read: %w", err)
	}
	defer transaction.Rollback()

	now := time.Now().UnixMilli()
	result, err := transaction.ExecContext(ctx, `
		UPDATE human_requests SET read_at = ?
		WHERE id = ? AND read_at IS NULL
	`, now, requestID)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("mark request read: %w", err)
	}
	affected, _ := result.RowsAffected()
	if affected == 0 {
		var exists int
		if err := transaction.QueryRowContext(ctx, `SELECT COUNT(*) FROM human_requests WHERE id = ?`, requestID).Scan(&exists); err != nil {
			return domain.HumanRequest{}, fmt.Errorf("inspect request read state: %w", err)
		}
		if exists == 0 {
			return domain.HumanRequest{}, repository.ErrNotFound
		}
	} else if err := store.insertEvent(ctx, transaction, "request.read", requestID, map[string]any{
		"read_at": now,
	}); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := transaction.Commit(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("commit request read state: %w", err)
	}
	return store.GetRequest(ctx, requestID)
}

func (store *Store) SaveRequestDraft(
	ctx context.Context,
	requestID string,
	content string,
	deviceID string,
) (domain.HumanRequest, error) {
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("begin save request draft: %w", err)
	}
	defer transaction.Rollback()

	now := time.Now().UnixMilli()
	var draft any
	var updatedAt any
	var draftDevice any
	if strings.TrimSpace(content) != "" {
		draft = content
		updatedAt = now
		draftDevice = nullString(strings.TrimSpace(deviceID))
	}
	result, err := transaction.ExecContext(ctx, `
		UPDATE human_requests
		SET draft_text = ?, draft_updated_at = ?, draft_device_id = ?
		WHERE id = ? AND status = 'pending'
	`, draft, updatedAt, draftDevice, requestID)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("save request draft: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		var status domain.RequestStatus
		if err := transaction.QueryRowContext(ctx, `SELECT status FROM human_requests WHERE id = ?`, requestID).Scan(&status); errors.Is(err, sql.ErrNoRows) {
			return domain.HumanRequest{}, repository.ErrNotFound
		} else if err != nil {
			return domain.HumanRequest{}, fmt.Errorf("inspect request draft state: %w", err)
		}
		return domain.HumanRequest{}, repository.ErrNotPending
	}
	if err := store.insertEvent(ctx, transaction, "request.draft", requestID, map[string]any{
		"has_draft": strings.TrimSpace(content) != "", "updated_at": updatedAt, "device_id": strings.TrimSpace(deviceID),
	}); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := transaction.Commit(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("commit request draft: %w", err)
	}
	return store.GetRequest(ctx, requestID)
}

func (store *Store) TouchClient(ctx context.Context, requestID string) error {
	_, err := store.database.ExecContext(ctx, `
		UPDATE human_requests SET client_last_seen_at = ? WHERE id = ? AND status = 'pending'
	`, time.Now().UnixMilli(), requestID)
	if err != nil {
		return fmt.Errorf("touch client: %w", err)
	}
	return nil
}

func (store *Store) ListDueAutoReplies(
	ctx context.Context,
	nowMilliseconds int64,
	limit int,
) ([]domain.HumanRequest, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := store.database.QueryContext(ctx, `
		SELECT `+requestColumns+` FROM human_requests
		WHERE status = 'pending' AND auto_reply_due_at IS NOT NULL AND auto_reply_due_at <= ?
		ORDER BY auto_reply_due_at LIMIT ?
	`, nowMilliseconds, limit)
	if err != nil {
		return nil, fmt.Errorf("list due auto replies: %w", err)
	}
	defer rows.Close()
	items := make([]domain.HumanRequest, 0)
	for rows.Next() {
		item, err := scanRequest(rows)
		if err != nil {
			return nil, fmt.Errorf("scan due auto reply: %w", err)
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) ExpireDue(ctx context.Context, nowSeconds int64) (int, error) {
	result, err := store.database.ExecContext(ctx, `
		UPDATE human_requests
		SET status = 'expired', updated_at = ?, claim_owner = NULL, claim_expires_at = NULL
		WHERE status = 'pending' AND expires_at <= ? AND stream_chunk_count = 0
	`, time.Now().UnixMilli(), nowSeconds)
	if err != nil {
		return 0, fmt.Errorf("expire due requests: %w", err)
	}
	affected, _ := result.RowsAffected()
	return int(affected), nil
}
