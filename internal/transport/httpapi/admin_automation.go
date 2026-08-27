package httpapi

import (
	"errors"
	"net/http"
	"strings"

	"iamllm/internal/domain"
)

func (server *Server) adminProfile(w http.ResponseWriter, r *http.Request) {
	item, err := server.control.Profile(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, item)
}
func (server *Server) adminSaveProfile(w http.ResponseWriter, r *http.Request) {
	var item domain.Profile
	if !decodeJSON(w, r, &item) {
		return
	}
	if strings.TrimSpace(item.DisplayName) == "" || strings.TrimSpace(item.Bio) == "" {
		writeAdminError(w, 400, "invalid_profile", "display_name and bio are required")
		return
	}
	saved, err := server.control.SaveProfile(r.Context(), item)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, saved)
}

func (server *Server) adminQuickReplies(w http.ResponseWriter, r *http.Request) {
	items, err := server.control.QuickReplies(r.Context(), r.URL.Query().Get("all") == "1")
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, map[string]any{"items": items})
}
func (server *Server) adminCreateQuickReply(w http.ResponseWriter, r *http.Request) {
	var item domain.QuickReply
	if !decodeJSON(w, r, &item) {
		return
	}
	if item.Category == "" {
		item.Category = "常用"
	}
	if strings.TrimSpace(item.Title) == "" || strings.TrimSpace(item.Content) == "" {
		writeAdminError(w, 400, "invalid_quick_reply", "title and content are required")
		return
	}
	saved, err := server.control.SaveQuickReply(r.Context(), item)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 201, saved)
}
func (server *Server) adminUpdateQuickReply(w http.ResponseWriter, r *http.Request) {
	item, err := server.control.QuickReply(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	var values map[string]any
	if !decodeJSON(w, r, &values) {
		return
	}
	mergeJSON(values, &item)
	saved, err := server.control.SaveQuickReply(r.Context(), item)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, saved)
}
func (server *Server) adminDeleteQuickReply(w http.ResponseWriter, r *http.Request) {
	if err := server.control.DeleteQuickReply(r.Context(), r.PathValue("id")); err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	w.WriteHeader(204)
}

func (server *Server) adminAutoRules(w http.ResponseWriter, r *http.Request) {
	items, err := server.control.AutoRules(r.Context())
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, map[string]any{"items": items})
}
func validateRule(item domain.AutoReplyRule) error {
	if strings.TrimSpace(item.Name) == "" || strings.TrimSpace(item.ResponseText) == "" {
		return errors.New("name and response_text are required")
	}
	if item.RuleType == "keyword" && strings.TrimSpace(item.Pattern) == "" {
		return errors.New("keyword rules require pattern")
	}
	if item.RuleType == "keyword" && item.MatchType != "contains" && item.MatchType != "exact" {
		return errors.New("match_type must be contains or exact")
	}
	if item.RuleType == "schedule" && (item.StartTime == "" || item.EndTime == "") {
		return errors.New("schedule rules require start_time and end_time")
	}
	if item.RuleType != "keyword" && item.RuleType != "schedule" {
		return errors.New("rule_type must be keyword or schedule")
	}
	if item.DelaySeconds < 0 || item.DelaySeconds > 300 {
		return errors.New("delay_seconds must be between 0 and 300")
	}
	for _, day := range item.Days {
		if day < 0 || day > 6 {
			return errors.New("days must contain values from 0 to 6")
		}
	}
	if len(item.Days) == 0 {
		item.Days = []int{0, 1, 2, 3, 4, 5, 6}
	}
	return nil
}
func (server *Server) adminCreateAutoRule(w http.ResponseWriter, r *http.Request) {
	var item domain.AutoReplyRule
	if !decodeJSON(w, r, &item) {
		return
	}
	if len(item.Days) == 0 {
		item.Days = []int{0, 1, 2, 3, 4, 5, 6}
	}
	if item.MatchType == "" {
		item.MatchType = "contains"
	}
	if err := validateRule(item); err != nil {
		writeAdminError(w, 400, "invalid_rule", err.Error())
		return
	}
	saved, err := server.control.SaveAutoRule(r.Context(), item)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 201, saved)
}
func (server *Server) adminUpdateAutoRule(w http.ResponseWriter, r *http.Request) {
	item, err := server.control.AutoRule(r.Context(), r.PathValue("id"))
	if err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	var values map[string]any
	if !decodeJSON(w, r, &values) {
		return
	}
	mergeJSON(values, &item)
	if err := validateRule(item); err != nil {
		writeAdminError(w, 400, "invalid_rule", err.Error())
		return
	}
	saved, err := server.control.SaveAutoRule(r.Context(), item)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, saved)
}
func (server *Server) adminDeleteAutoRule(w http.ResponseWriter, r *http.Request) {
	if err := server.control.DeleteAutoRule(r.Context(), r.PathValue("id")); err != nil {
		server.writeRepositoryError(w, r, err)
		return
	}
	w.WriteHeader(204)
}
func (server *Server) adminPreviewAutoRule(w http.ResponseWriter, r *http.Request) {
	var p struct {
		Text string `json:"text"`
	}
	if !decodeJSON(w, r, &p) {
		return
	}
	item, err := server.control.PreviewAutoRule(r.Context(), p.Text)
	if err != nil {
		server.internalError(w, r, err)
		return
	}
	writeJSON(w, 200, map[string]any{"matched": item != nil, "rule": item})
}
