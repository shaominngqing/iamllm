(() => {
  const root = document.querySelector(".admin-console");
  if (!root) return;

  const $ = (selector, parent = document) => parent.querySelector(selector);
  const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
  function tabOperatorId() {
    try {
      let id = sessionStorage.getItem("iamllm_operator_id");
      if (!id) {
        const random = crypto.randomUUID
          ? crypto.randomUUID().replaceAll("-", "")
          : `${Date.now()}_${Math.random().toString(36).slice(2)}`;
        id = `operator_${random}`;
        sessionStorage.setItem("iamllm_operator_id", id);
      }
      return id;
    } catch {
      return `operator_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    }
  }
  const state = {
    overview: null,
    requests: [],
    selectedRequestId: null,
    selectedRequestStatus: null,
    requestFilter: "pending",
    quickReplies: [],
    rules: [],
    apiKeys: [],
    profile: null,
    lastCreatedKey: null,
    selectedRequestDetail: null,
    contextView: "focus",
    knownRequestIds: new Set(),
    newArrivalIds: new Set(),
    queueLoaded: false,
    queueSerial: 0,
    detailSerial: 0,
    isSending: false,
    queueRefreshPending: false,
    queueJustCleared: false,
    autoOpen: true,
    operatorId: tabOperatorId(),
    claimedRequestId: null,
    claimRenewAt: 0,
    presenceRefreshAt: 0,
    selectedRequestClaimConflict: false,
  };
  const sectionCopy = {
    cockpit: ["API OPERATIONS", "概览"],
    inbox: ["LIVE REQUESTS", "请求队列"],
    keys: ["ACCESS CONTROL", "API 密钥"],
    integration: ["DEVELOPER EXPERIENCE", "接入指南"],
    automation: ["RESPONSE AUTOMATION", "自动回复"],
    settings: ["SERVICE CONFIGURATION", "服务设置"],
  };
  let toastTimer;

  try {
    state.autoOpen = localStorage.getItem("iamllm_auto_open") !== "off";
    state.contextView = localStorage.getItem("iamllm_context_view") === "full" ? "full" : "focus";
  } catch {
    state.autoOpen = true;
    state.contextView = "focus";
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    return element;
  }

  function toast(message, isError = false) {
    const box = $("#toast");
    box.textContent = message;
    box.classList.toggle("error", isError);
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), 2800);
  }

  async function copyText(value, successMessage = "已复制") {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const temporary = make("textarea");
      temporary.value = value;
      document.body.append(temporary);
      temporary.select();
      document.execCommand("copy");
      temporary.remove();
    }
    toast(successMessage, false);
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, { ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      let detail = payload?.detail || `请求失败（${response.status}）`;
      if (Array.isArray(detail)) detail = detail.map((item) => item.msg).join("；");
      const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function statusLabel(status) {
    return { pending: "待回答", answered: "已回答", expired: "已过期" }[status] || status;
  }

  function formatTime(value) {
    if (!value) return "—";
    const milliseconds = value > 10_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    }).format(new Date(milliseconds));
  }

  function latencyLabel(seconds) {
    if (!seconds) return "—";
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
  }

  function contextSizeLabel(characters) {
    const count = Number(characters || 0);
    if (count < 1_000) return `${count} 字符`;
    if (count < 1_000_000) return `${(count / 1_000).toFixed(count < 10_000 ? 1 : 0)}K 字符`;
    return `${(count / 1_000_000).toFixed(1)}M 字符`;
  }

  function waitingLabel(createdAt) {
    const seconds = Math.max(0, Math.floor(Date.now() / 1000 - createdAt));
    if (seconds < 60) return "刚刚到";
    if (seconds < 3600) return `已等 ${Math.floor(seconds / 60)} 分钟`;
    return `已等 ${Math.floor(seconds / 3600)} 小时`;
  }

  function updateStreamDeadline(element) {
    const remaining = Math.max(0, Number(element.dataset.expiresAt || 0) * 1000 - Date.now());
    const seconds = Math.ceil(remaining / 1000);
    const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    element.textContent = element.dataset.mode === "idle"
      ? `空闲收尾 ${clock} · 发一段就重置`
      : `等待首段 ${clock}`;
    element.classList.toggle("urgent", seconds <= 30);
  }

  function releaseClaim(requestId, { beacon = false } = {}) {
    if (!requestId) return;
    const path = `/admin/api/requests/${encodeURIComponent(requestId)}/claim/release`;
    const body = JSON.stringify({ operator_id: state.operatorId });
    if (beacon && navigator.sendBeacon) {
      navigator.sendBeacon(path, new Blob([body], { type: "application/json" }));
      return;
    }
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  }

  async function claimRequest(item) {
    try {
      const claimed = await api(`/admin/api/requests/${encodeURIComponent(item.id)}/claim`, {
        method: "POST",
        body: { operator_id: state.operatorId },
      });
      state.claimedRequestId = item.id;
      state.claimRenewAt = Date.now() + 10_000;
      state.selectedRequestClaimConflict = false;
      Object.assign(item, claimed, { claimConflict: false });
      return item;
    } catch (error) {
      if (error.status !== 409) throw error;
      if (state.claimedRequestId === item.id) state.claimedRequestId = null;
      state.selectedRequestClaimConflict = true;
      item.claimConflict = true;
      return item;
    }
  }

  function readDraft(requestId) {
    try { return localStorage.getItem(`iamllm_draft_${requestId}`) || ""; }
    catch { return ""; }
  }

  function saveDraft(requestId, value) {
    try {
      if (value) localStorage.setItem(`iamllm_draft_${requestId}`, value);
      else localStorage.removeItem(`iamllm_draft_${requestId}`);
    } catch { /* Draft persistence is a convenience, not a blocker. */ }
  }

  function activeComposerHasText() {
    const textarea = $("#request-detail .answer-composer textarea[name='answer']");
    return Boolean(textarea?.value.trim());
  }

  function currentRoute() {
    const route = location.hash.replace(/^#/, "").split("/").filter(Boolean);
    if (route[0] === "persona") route[0] = "settings";
    return { section: sectionCopy[route[0]] ? route[0] : "cockpit", id: route[1] || null };
  }

  function showSection(section) {
    if (section !== "inbox" && state.claimedRequestId) {
      const claimed = state.claimedRequestId;
      state.claimedRequestId = null;
      releaseClaim(claimed);
    }
    $$(".console-nav button[data-section]").forEach((button) => {
      button.classList.toggle("active", button.dataset.section === section);
    });
    $$(".console-section").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.panel === section);
    });
    const copy = sectionCopy[section];
    $("#section-kicker").textContent = copy[0];
    $("#section-title").textContent = copy[1];
    if (section === "inbox") {
      const routeId = currentRoute().id;
      loadRequests({ preferredId: routeId, reason: "enter", forceDetail: Boolean(routeId) });
    }
    if (section === "automation") loadAutomation();
    if (section === "keys") loadApiKeys();
    if (section === "integration") renderIntegration();
    if (section === "settings" && state.profile) renderServiceSettings();
  }

  async function loadOverview({ silent = false } = {}) {
    try {
      const data = await api("/admin/api/overview");
      state.overview = data;
      state.profile = data.profile;
      $("#metric-pending").textContent = data.pending;
      $("#metric-answered").textContent = data.answered_today;
      $("#metric-automated").textContent = data.automated_today;
      $("#metric-latency").textContent = latencyLabel(data.avg_response_seconds);
      $("#nav-pending").textContent = data.pending;
      $("#welcome-name").textContent = data.profile.display_name;
      $("#vital-availability").textContent = data.profile.availability || "未设置状态说明";
      $("#vital-rules").textContent = `${data.active_rules} 条`;
      $("#vital-notifications").textContent = data.notifications_enabled ? "已接通" : "未配置";
      $("#settings-notifications").textContent = data.notifications_enabled ? "已接通" : "未配置";
      $("#test-notification").disabled = !data.notifications_enabled;
      return data;
    } catch (error) {
      if (!silent) toast(error.message, true);
      return null;
    }
  }

  async function loadRequests({ preferredId = null, reason = "manual", forceDetail = false } = {}) {
    const list = $("#request-list");
    const serial = ++state.queueSerial;
    list.setAttribute("aria-busy", "true");
    try {
      const data = await api(`/admin/api/requests?filter=${encodeURIComponent(state.requestFilter)}`);
      if (serial !== state.queueSerial) return;
      if (state.requestFilter === "pending") {
        data.items.sort((first, second) =>
          first.created_at - second.created_at || first.updated_at - second.updated_at
        );
      }
      const incomingIds = new Set(data.items.map((item) => item.id));
      const arrivals = state.queueLoaded
        ? data.items.filter((item) => !state.knownRequestIds.has(item.id))
        : [];
      const selectedStillVisible = data.items.some((item) => item.id === state.selectedRequestId);

      state.requests = data.items;
      state.knownRequestIds = incomingIds;
      state.queueLoaded = true;
      arrivals.forEach((item) => state.newArrivalIds.add(item.id));
      renderRequestList();
      updateActiveQueueMetadata();

      if (selectedStillVisible && !forceDetail) {
        if (arrivals.length) showNewRequestNotice(arrivals);
        return;
      }

      let targetId = null;
      if (preferredId && state.requests.some((item) => item.id === preferredId)) {
        targetId = preferredId;
      } else if (state.requests.length) {
        const shouldAutoOpen = reason !== "realtime" || state.autoOpen;
        if (shouldAutoOpen) targetId = state.requests[0].id;
      }

      if (targetId) {
        await selectRequest(targetId, false, { focusComposer: true, force: true });
      } else if (preferredId && reason === "enter") {
        await selectRequest(preferredId, false, { focusComposer: false, force: true });
      } else {
        state.selectedRequestId = null;
        state.selectedRequestStatus = null;
        state.selectedRequestDetail = null;
        history.replaceState(null, "", "#inbox");
        renderEmptyDetail({ completed: reason === "after-answer" || state.queueJustCleared });
        if (arrivals.length) showNewRequestNotice(arrivals);
      }
    } catch (error) {
      list.replaceChildren(make("div", "panel-loading", error.message));
    } finally {
      list.removeAttribute("aria-busy");
    }
  }

  function renderRequestList() {
    const list = $("#request-list");
    list.replaceChildren();
    if (!state.requests.length) {
      const empty = make("div", "detail-placeholder");
      empty.append(make("span", "", "✓"), make("h3", "", "队列已经清空"), make("p", "", "当前没有需要处理的请求。"));
      list.append(empty);
      return;
    }
    state.requests.forEach((item, index) => {
      const row = make("button", `request-row${state.newArrivalIds.has(item.id) ? " new-arrival" : ""}`);
      row.type = "button";
      row.dataset.requestId = item.id;
      row.classList.toggle("active", item.id === state.selectedRequestId);

      const head = make("div", "request-row-head");
      const status = make("span", `status status-${item.status}`, statusLabel(item.status));
      if (state.requestFilter === "pending") status.textContent = `${index + 1} · ${statusLabel(item.status)}`;
      head.append(status, make("time", "", item.status === "pending" ? waitingLabel(item.created_at) : formatTime(item.created_at)));
      const preview = make("p", "", item.preview);
      preview.title = item.preview;
      row.append(head, preview);

      const foot = make("div", "request-row-foot");
      const sourceLabels = {
        web_chat: "访客聊天",
        openai_responses: "OpenAI Responses",
        anthropic_messages: "Claude Messages",
        gemini_generate_content: "Gemini Content",
        api: "OpenAI Chat",
      };
      foot.append(make("span", "", sourceLabels[item.source] || "API"));
      if (Number(item.context_chars || 0) >= 20_000) {
        foot.append(make("span", "large-context-badge", contextSizeLabel(item.context_chars)));
      }
      if (Number(item.tool_count || 0) > 0) {
        foot.append(make("span", "tool-count-badge", `工具 ${item.tool_count}`));
      }
      if (item.conversation_id) foot.append(make("span", "", "有上下文"));
      if (item.stream_requested || item.stream_chunk_count) {
        const segmentLabel = item.stream_requested ? "直播中" : "回答中";
        foot.append(make("span", "stream-row-badge", item.stream_chunk_count
          ? `${segmentLabel} · ${item.stream_chunk_count} 段`
          : "等待流式开口"));
      }
      if (item.auto_reply_due_at && item.status === "pending") foot.append(make("span", "auto-due", `自动挡 · ${item.auto_reply_label}`));
      if (item.claim_active && item.claim_owner !== state.operatorId) foot.append(make("span", "claim-row-badge", "另一后台接管"));
      if (readDraft(item.id)) foot.append(make("span", "draft-badge", "有草稿"));
      row.append(foot);
      row.addEventListener("click", () => selectRequest(item.id, true, { focusComposer: true }));
      list.append(row);
    });
  }

  async function selectRequest(requestId, updateHash = true, { focusComposer = false, force = false } = {}) {
    if (!force && requestId === state.selectedRequestId && $("#request-detail .detail-shell")) return;
    const previousClaim = state.claimedRequestId;
    if (previousClaim && previousClaim !== requestId) {
      state.claimedRequestId = null;
      releaseClaim(previousClaim);
    }
    const serial = ++state.detailSerial;
    state.selectedRequestId = requestId;
    state.queueJustCleared = false;
    state.newArrivalIds.delete(requestId);
    $$(".request-row").forEach((row) => row.classList.toggle("active", row.dataset.requestId === requestId));
    if (updateHash) history.replaceState(null, "", `#inbox/${requestId}`);
    updateNewRequestNotice();
    const detail = $("#request-detail");
    detail.replaceChildren(make("div", "panel-loading", "正在搬运完整上下文……"));
    try {
      let item = await api(`/admin/api/requests/${encodeURIComponent(requestId)}`);
      if (serial !== state.detailSerial || state.selectedRequestId !== requestId) return;
      if (item.status === "pending") item = await claimRequest(item);
      if (serial !== state.detailSerial || state.selectedRequestId !== requestId) {
        if (state.claimedRequestId === requestId) releaseClaim(requestId);
        return;
      }
      state.selectedRequestStatus = item.status;
      state.selectedRequestDetail = item;
      if (item.status !== "pending" && state.claimedRequestId === requestId) {
        state.claimedRequestId = null;
      }
      renderRequestDetail(item);
      renderRequestList();
      if (focusComposer && item.status === "pending") {
        setTimeout(() => $("#request-detail textarea[name='answer']")?.focus(), 30);
      }
    } catch (error) {
      detail.replaceChildren(make("div", "panel-loading", error.message));
    }
  }

  function renderEmptyDetail({ completed = false } = {}) {
    state.selectedRequestDetail = null;
    const empty = make("div", "detail-placeholder");
    if (completed) {
      empty.classList.add("queue-complete");
      empty.append(make("span", "", "✓"), make("h3", "", "这轮清空了"), make("p", "", "下一条问题到达时会自动接进来。你可以先去喝口水，模型不需要假装一直在线。"));
      const actions = make("div", "inline-actions");
      const history = make("button", "soft-action", "看看刚才的回答");
      history.type = "button";
      history.addEventListener("click", () => switchRequestFilter("answered"));
      const cockpit = make("button", "soft-action", "回驾驶舱");
      cockpit.type = "button";
      cockpit.addEventListener("click", () => { location.hash = "#cockpit"; });
      actions.append(history, cockpit);
      empty.append(actions);
    } else if (state.requests.length && !state.autoOpen) {
      empty.append(make("span", "", "↳"), make("h3", "", `${state.requests.length} 个问题正在等你接单`), make("p", "", "“空闲自动接单”已关闭，点击左侧任意问题开始。"));
    } else {
      empty.append(make("span", "", "☕"), make("h3", "", "暂时不用营业"), make("p", "", "有新问题时会自动出现在这里，不需要刷新。"));
    }
    $("#request-detail").replaceChildren(empty);
  }

  function showNewRequestNotice(arrivals) {
    if (!arrivals.length) return;
    const notice = $("#new-request-notice");
    const protectedDraft = activeComposerHasText();
    $("#new-request-copy").textContent = arrivals.length === 1
      ? protectedDraft ? "新问题已入队，你的草稿没有被打断" : "新问题已入队，当前问题继续处理"
      : protectedDraft ? `${arrivals.length} 个新问题已入队，你的草稿没有被打断` : `${arrivals.length} 个新问题已入队`;
    notice.hidden = false;
  }

  function updateNewRequestNotice() {
    const notice = $("#new-request-notice");
    const visibleArrivals = state.requests.filter((item) => state.newArrivalIds.has(item.id));
    if (!visibleArrivals.length) notice.hidden = true;
    else showNewRequestNotice(visibleArrivals);
  }

  const roleLabels = {
    system: "系统指令",
    developer: "开发者指令",
    user: "当前输入",
    assistant: "助手历史",
    tool: "工具结果",
  };

  function messagePlainText(message) {
    const content = message?.content;
    let text = "";
    if (typeof content === "string") text = content;
    else if (Array.isArray(content)) {
      text = content.filter((part) => part?.type === "text").map((part) => part.text || "").join("\n");
    }
    const calls = (message?.tool_calls || []).map((call) =>
      `${call.function?.name || "unknown"}(${call.function?.arguments || "{}"})`
    );
    return [text, ...calls].filter(Boolean).join("\n");
  }

  function messageCharacterCount(message) {
    return messagePlainText(message).length;
  }

  function appendExpandableText(container, text, { limit = 1_800 } = {}) {
    const value = String(text || "");
    const content = make("div", "content-text");
    const long = value.length > limit;
    const collapsed = long ? `${value.slice(0, limit).trimEnd()}\n\n… 已折叠 ${contextSizeLabel(value.length - limit)}` : value;
    content.textContent = collapsed;
    container.append(content);
    if (!value) return;

    const actions = make("div", "content-actions");
    if (long) {
      const toggle = make("button", "", "展开全文");
      toggle.type = "button";
      toggle.addEventListener("click", () => {
        const expanded = toggle.dataset.expanded === "true";
        toggle.dataset.expanded = expanded ? "false" : "true";
        toggle.textContent = expanded ? "展开全文" : "收起全文";
        content.textContent = expanded ? collapsed : value;
      });
      actions.append(toggle);
    }
    const copy = make("button", "", "复制原文");
    copy.type = "button";
    copy.addEventListener("click", () => copyText(value, "原文已复制"));
    actions.append(copy);
    container.append(actions);
  }

  function appendMessageContent(container, content, options = {}) {
    if (typeof content === "string") {
      appendExpandableText(container, content, options);
      return;
    }
    if (!Array.isArray(content)) return;
    content.forEach((part) => {
      if (part.type === "text") appendExpandableText(container, part.text, options);
      if (part.type === "image_url" && part.image_url?.url) {
        const link = make("a");
        link.href = part.image_url.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        const image = make("img");
        image.src = part.image_url.url;
        image.alt = "对话中的图片";
        image.loading = "lazy";
        link.append(image);
        container.append(link);
      }
    });
  }

  function buildMessageBubble(message, { limit = 1_800, focus = false } = {}) {
    const bubble = make("article", `context-message ${message.role || "user"}${focus ? " focus-message" : ""}`);
    const head = make("div", "context-message-head");
    head.append(
      make("span", "role-label", roleLabels[message.role] || message.role || "消息"),
      make("span", "context-message-size", contextSizeLabel(messageCharacterCount(message)))
    );
    bubble.append(head);
    appendMessageContent(bubble, message.content, { limit });
    (message.tool_calls || []).forEach((toolCall) => {
      const tool = make("div", "tool-call-card");
      tool.append(make("span", "", "调用工具"), make("strong", "", toolCall.function?.name || "unknown"));
      appendExpandableText(tool, toolCall.function?.arguments || "{}", { limit: 1_000 });
      bubble.append(tool);
    });
    return bubble;
  }

  function buildLazyMessageGroup(label, description, messages) {
    if (!messages.length) return null;
    const details = make("details", "context-group");
    const summary = make("summary");
    const copy = make("div");
    copy.append(make("b", "", label), make("span", "", description));
    const characters = messages.reduce((total, message) => total + messageCharacterCount(message), 0);
    summary.append(copy, make("em", "", `${messages.length} 条 · ${contextSizeLabel(characters)}`));
    const body = make("div", "context-group-body");
    details.append(summary, body);
    details.addEventListener("toggle", () => {
      if (!details.open || body.dataset.loaded === "true") return;
      body.dataset.loaded = "true";
      messages.forEach((message) => body.append(buildMessageBubble(message, { limit: 1_500 })));
    });
    return details;
  }

  function buildToolsGroup(tools) {
    if (!tools?.length) return null;
    const details = make("details", "context-group tool-definition-group");
    const summary = make("summary");
    const copy = make("div");
    copy.append(make("b", "", "可调用工具"), make("span", "", "来自客户端的函数定义，展开后按工具查看"));
    summary.append(copy, make("em", "", `${tools.length} 个定义`));
    const body = make("div", "context-group-body available-tools");
    details.append(summary, body);
    details.addEventListener("toggle", () => {
      if (!details.open || body.dataset.loaded === "true") return;
      body.dataset.loaded = "true";
      tools.forEach((tool) => {
        const toolDetails = make("details");
        toolDetails.append(make("summary", "", tool.function?.name || "unknown"));
        const toolBody = make("div", "tool-definition-body");
        toolDetails.append(toolBody);
        toolDetails.addEventListener("toggle", () => {
          if (!toolDetails.open || toolBody.dataset.loaded === "true") return;
          toolBody.dataset.loaded = "true";
          if (tool.function?.description) toolBody.append(make("p", "", tool.function.description));
          appendExpandableText(toolBody, JSON.stringify(tool.function?.parameters || {}, null, 2), { limit: 2_000 });
        });
        body.append(toolDetails);
      });
    });
    return details;
  }

  function focusMessageIndex(messages) {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index]?.role === "user" && messagePlainText(messages[index]).trim()) return index;
    }
    return Math.max(0, messages.length - 1);
  }

  function buildContextThread(item) {
    const thread = make("div", `context-thread context-view-${state.contextView}`);
    const messages = item.messages || [];
    const totalChars = Number(item.context_chars || messages.reduce((sum, message) => sum + messageCharacterCount(message), 0));
    const overview = make("section", "context-overview");
    const overviewCopy = make("div");
    overviewCopy.append(
      make("p", "eyebrow", "CONTEXT MAP"),
      make("strong", "", state.contextView === "focus" ? "重点视图" : "完整视图"),
      make("span", "", state.contextView === "focus" ? "机器上下文仍完整保留，只是默认收好。" : "所有消息按协议顺序展示，超长内容仍按项折叠。")
    );
    const stats = make("div", "context-stats");
    stats.append(
      make("span", "", `${messages.length} 条消息`),
      make("span", "", contextSizeLabel(totalChars)),
      make("span", "", `${Number(item.system_count || 0)} 条指令`),
      make("span", "", `${Number(item.tool_count || 0)} 个工具项`)
    );
    overview.append(overviewCopy, stats);
    thread.append(overview);

    const focusIndex = focusMessageIndex(messages);
    if (state.contextView === "full") {
      messages.forEach((message) => thread.append(buildMessageBubble(message, { limit: 2_200, focus: message === messages[focusIndex] })));
      const toolsGroup = buildToolsGroup(item.tools || []);
      if (toolsGroup) thread.append(toolsGroup);
      return thread;
    }

    const focusCard = make("section", "request-focus-card");
    focusCard.append(make("div", "focus-card-label", "现在处理这条"), buildMessageBubble(messages[focusIndex] || { role: "user", content: "新请求" }, { limit: 2_400, focus: true }));
    thread.append(focusCard);

    const instructionMessages = messages.filter((message, index) => index !== focusIndex && ["system", "developer"].includes(message.role));
    const toolMessages = messages.filter((message, index) => index !== focusIndex && (message.role === "tool" || message.tool_calls?.length));
    const historyMessages = messages.filter((message, index) =>
      index !== focusIndex && !["system", "developer", "tool"].includes(message.role) && !message.tool_calls?.length
    );
    const groups = [
      buildLazyMessageGroup("系统与开发者指令", "客户端的行为约束与运行说明", instructionMessages),
      buildLazyMessageGroup("对话历史", "此前的用户与助手消息", historyMessages),
      buildLazyMessageGroup("工具过程", "函数调用、工具参数与执行结果", toolMessages),
      buildToolsGroup(item.tools || []),
    ].filter(Boolean);
    if (groups.length) {
      const stack = make("section", "context-group-stack");
      stack.append(...groups);
      thread.append(stack);
    }
    return thread;
  }

  function setContextView(view, item) {
    state.contextView = view === "full" ? "full" : "focus";
    try { localStorage.setItem("iamllm_context_view", state.contextView); }
    catch { /* View preference is optional. */ }
    const current = $("#request-detail .context-thread");
    if (current) current.replaceWith(buildContextThread(item));
    $$("#request-detail [data-context-view]").forEach((button) => {
      button.classList.toggle("active", button.dataset.contextView === state.contextView);
    });
  }

  function cycleRequest(direction) {
    if (state.requests.length < 2) return;
    const currentIndex = state.requests.findIndex((item) => item.id === state.selectedRequestId);
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + direction + state.requests.length) % state.requests.length;
    selectRequest(state.requests[nextIndex].id, true, { focusComposer: true });
  }

  function updateActiveQueueMetadata() {
    if (state.selectedRequestStatus !== "pending") return;
    const index = state.requests.findIndex((request) => request.id === state.selectedRequestId);
    const item = state.requests[index];
    const position = $("#request-detail .queue-position");
    if (position && item && index >= 0) {
      position.textContent = `队列 ${index + 1}/${state.requests.length} · ${waitingLabel(item.created_at)}`;
    }
    $$("#request-detail .detail-navigation button").forEach((button) => {
      button.disabled = state.requests.length < 2;
    });
  }

  function renderRequestDetail(item) {
    const shell = make("div", `detail-shell${item.status === "pending" ? "" : " detail-readonly"}`);
    const top = make("header", "detail-top");
    const title = make("div");
    const index = state.requests.findIndex((request) => request.id === item.id);
    const queuePosition = index >= 0 && state.requestFilter === "pending"
      ? `队列 ${index + 1}/${state.requests.length} · ${waitingLabel(item.created_at)}`
      : item.conversation_id ? "FULL CONVERSATION" : "SINGLE REQUEST";
    const requestTitle = make("h3", "", item.preview);
    requestTitle.title = item.preview;
    title.append(make("p", "eyebrow queue-position", queuePosition), requestTitle);
    const identity = make("div", "detail-identity");
    const contextToggle = make("div", "context-view-toggle");
    [["focus", "重点"], ["full", "完整"]].forEach(([view, label]) => {
      const button = make("button", view === state.contextView ? "active" : "", label);
      button.type = "button";
      button.dataset.contextView = view;
      button.addEventListener("click", () => setContextView(view, item));
      contextToggle.append(button);
    });
    identity.append(contextToggle);
    if (item.status === "pending" || state.requests.length > 1) {
      const navigation = make("div", "detail-navigation");
      const previous = make("button", "", "↑ 上一条"); previous.type = "button"; previous.title = "快捷键 K";
      const next = make("button", "", "下一条 ↓"); next.type = "button"; next.title = "快捷键 J";
      previous.disabled = state.requests.length < 2;
      next.disabled = state.requests.length < 2;
      previous.addEventListener("click", () => cycleRequest(-1));
      next.addEventListener("click", () => cycleRequest(1));
      navigation.append(previous, next);
      identity.append(navigation);
    }
    identity.append(make("span", `status status-${item.status}`, statusLabel(item.status)), make("code", "", item.id));
    top.append(title, identity);

    shell.append(top, buildContextThread(item));

    if (item.status === "pending") {
      const presence = make("div", `request-presence ${item.client_connected ? "online" : "offline"}`);
      presence.id = "request-presence";
      presence.textContent = item.client_connected
        ? "● 客户端在线 · 你发出的 chunk 会立即送达"
        : item.client_last_seen_at
          ? "○ 客户端可能已断开 · 响应仍会保存并可稍后查询"
          : "○ 暂时没收到客户端心跳 · API 调用方可能正在轮询";
      shell.append(presence);
      if (item.auto_reply_due_at) {
        const seconds = Math.max(0, Math.ceil((item.auto_reply_due_at - Date.now()) / 1000));
        shell.append(make("div", "auto-countdown", `⚡「${item.auto_reply_label}」将在约 ${seconds} 秒后自动发送。现在手动提交会取消该规则。`));
      }
      if (item.claimConflict) {
        const conflict = make("div", "claim-conflict");
        conflict.append(
          make("strong", "", "另一张后台正在打字"),
          make("p", "", "这个请求正在另一个控制台标签页中处理。接管释放后即可继续。")
        );
        const retry = make("button", "soft-action", "重新尝试接管");
        retry.type = "button";
        retry.addEventListener("click", () => selectRequest(item.id, false, { focusComposer: true, force: true }));
        conflict.append(retry);
        shell.append(conflict);
      } else {
        shell.append(buildAnswerComposer(item));
      }
    } else if (item.status === "answered") {
      let summary = item.response?.content;
      if (!summary && item.response?.tool_calls) {
        const call = item.response.tool_calls[0];
        summary = `已调用工具 ${call.function.name}\n${call.function.arguments}`;
      }
      const answered = make("div", "answered-box", summary || "已回答");
      const who = item.answer_source === "automation" ? "自动挡发送" : "你亲自发送";
      answered.prepend(make("p", "eyebrow", `${who} · ${formatTime(item.answered_at)}`));
      shell.append(answered);
    } else {
      shell.append(make("div", "answered-box", "这个请求已经过期，无法再提交响应。"));
    }
    $("#request-detail").replaceChildren(shell);
  }

  function buildAnswerComposer(item) {
    const composer = make("form", "answer-composer");
    const isSegmentedReply = true;
    const isRealtimeStream = Boolean(item.stream_requested);
    const streamChunks = [...(item.stream_chunks || [])];
    let streamCounter = null;
    let streamList = null;
    if (isSegmentedReply) {
      const livePanel = make("section", "live-stream-panel");
      const liveHead = make("div", "live-stream-head");
      const title = make("div");
      title.append(
        make("span", "live-stream-dot", "LIVE"),
        make("strong", "", isRealtimeStream ? " 流式响应进行中" : " 分段响应")
      );
      streamCounter = make("span", "live-stream-counter");
      const liveMeta = make("div", "live-stream-meta");
      const streamDeadline = make("span", "stream-deadline");
      streamDeadline.dataset.streamDeadline = "true";
      liveMeta.append(streamCounter, streamDeadline);
      liveHead.append(title, liveMeta);
      streamList = make("div", "stream-segment-list");
      livePanel.append(
        liveHead,
        make("p", "live-stream-help", isRealtimeStream
          ? "非空 Enter：立刻发这一段 · 已发过后空 Enter：结束 · Shift + Enter：段内换行"
          : "非空 Enter：生成一个 chunk · 空 Enter：结束回答 · 当前调用方结束后才能一次取回全文"),
        streamList
      );
      composer.append(livePanel);
    }
    const quickStrip = make("div", "quick-strip");
    state.quickReplies.filter((reply) => reply.active).forEach((reply) => {
      const chip = make("button", "quick-chip", reply.title);
      chip.type = "button";
      chip.title = reply.content;
      chip.addEventListener("click", () => {
        const textarea = $("textarea[name='answer']", composer);
        textarea.value = reply.content;
        saveDraft(item.id, textarea.value);
        updateDraftStatus();
        textarea.focus();
      });
      quickStrip.append(chip);
    });
    if (!quickStrip.children.length) {
      const manage = make("button", "quick-chip", "＋ 去配置快捷话术");
      manage.type = "button";
      manage.addEventListener("click", () => { location.hash = "#automation"; });
      quickStrip.append(manage);
    }
    composer.append(quickStrip);

    let typeSelect = null;
    let toolName = null;
    let toolArguments = null;
    if (item.tools?.length) {
      const modeRow = make("div", "form-two");
      const typeLabel = make("label", "", "回复方式");
      typeSelect = make("select");
      typeSelect.name = "response_type";
      [["text", "直接回答"], ["tool_call", "调用工具"]].forEach(([value, label]) => {
        const option = make("option", "", label); option.value = value; typeSelect.append(option);
      });
      typeLabel.append(typeSelect);
      const toolLabel = make("label", "", "工具");
      toolName = make("select"); toolName.name = "tool_name"; toolName.disabled = true;
      item.tools.forEach((tool) => { const option = make("option", "", tool.function.name); option.value = tool.function.name; toolName.append(option); });
      toolLabel.append(toolName);
      modeRow.append(typeLabel, toolLabel);
      composer.append(modeRow);
    }
    const textarea = make("textarea");
    textarea.name = "answer";
    textarea.maxLength = 50_000;
    textarea.placeholder = isSegmentedReply
      ? (isRealtimeStream
        ? "写第一段，按 Enter 就会立即发送给客户端……"
        : "写第一段，按 Enter 生成 chunk；空回车结束……")
      : "输入你真正想说的话……（Enter 发送，Shift + Enter 换行）";
    textarea.value = readDraft(item.id);
    composer.append(textarea);
    if (item.tools?.length) {
      toolArguments = make("textarea");
      toolArguments.name = "tool_arguments";
      toolArguments.value = "{}";
      toolArguments.placeholder = "工具参数 JSON";
      toolArguments.hidden = true;
      composer.append(toolArguments);
      typeSelect.addEventListener("change", () => {
        const toolMode = typeSelect.value === "tool_call";
        textarea.hidden = toolMode;
        toolArguments.hidden = !toolMode;
        toolName.disabled = !toolMode;
        updateDraftStatus();
      });
    }
    const footer = make("div", "composer-footer");
    const draftStatus = make("small", "draft-status");
    const submit = make("button", "primary-action");
    submit.type = "submit";

    function renderStreamLedger() {
      if (!isSegmentedReply) return;
      streamCounter.textContent = streamChunks.length
        ? `${isRealtimeStream ? "已送达" : "已生成"} ${streamChunks.length} 个 chunk`
        : "还没开口";
      const deadline = $("[data-stream-deadline]", composer);
      if (deadline) {
        deadline.dataset.expiresAt = String(item.expires_at || 0);
        deadline.dataset.mode = streamChunks.length ? "idle" : "first";
        updateStreamDeadline(deadline);
      }
      streamList.replaceChildren();
      if (!streamChunks.length) {
        streamList.append(make("div", "stream-segment-empty", "第一下空回车不会结束——我猜你只是清了清嗓子。"));
      } else {
        streamChunks.forEach((chunk) => {
          const segment = make("div", "stream-segment");
          segment.append(
            make("span", "stream-segment-index", String(chunk.position)),
            make("span", "stream-segment-content", chunk.content)
          );
          streamList.append(segment);
        });
        streamList.scrollTop = streamList.scrollHeight;
      }
      if (typeSelect && streamChunks.length) {
        typeSelect.value = "text";
        typeSelect.disabled = true;
        toolName.disabled = true;
      }
    }

    function updateDraftStatus() {
      const textMode = (typeSelect?.value || "text") === "text";
      if (isSegmentedReply && textMode) {
        if (textarea.value.trim()) {
          draftStatus.textContent = isRealtimeStream
            ? "这次 Enter 只发送当前这一段"
            : "这次 Enter 会生成当前段的 chunk";
          submit.textContent = `${isRealtimeStream ? "发送" : "生成"}第 ${streamChunks.length + 1} 个 chunk →`;
        } else if (streamChunks.length) {
          draftStatus.textContent = isRealtimeStream
            ? "输入为空，再按 Enter 就正式收尾"
            : "输入为空，再按 Enter 就把完整答案发出去";
          submit.textContent = isRealtimeStream
            ? "结束流式回复 ✓"
            : "发送完整回复 ✓";
        } else {
          draftStatus.textContent = "先写第一段 · 空回车不会误结束";
          submit.textContent = "先写第一段";
        }
      } else {
        draftStatus.textContent = textarea.value
          ? "草稿已自动保存 · Enter 发送 · Shift + Enter 换行"
          : "Enter 发送 · Shift + Enter 换行 · J/K 切换问题";
        submit.textContent = "提交响应 →";
      }
    }
    textarea.addEventListener("input", () => {
      saveDraft(item.id, textarea.value);
      updateDraftStatus();
      renderRequestList();
    });
    renderStreamLedger();
    updateDraftStatus();
    footer.append(draftStatus);
    footer.append(submit);
    composer.append(footer);

    async function advanceQueue() {
      saveDraft(item.id, "");
      state.claimedRequestId = null;
      state.claimRenewAt = 0;
      state.selectedRequestId = null;
      state.selectedRequestStatus = null;
      state.requestFilter = "pending";
      state.queueRefreshPending = false;
      state.queueJustCleared = true;
      history.replaceState(null, "", "#inbox");
      syncRequestFilterButtons();
      await Promise.all([
        loadOverview(),
        loadRequests({ reason: "after-answer", forceDetail: true }),
      ]);
      toast(state.requests.length
        ? `收尾完成，自动接到下一条。队列还剩 ${state.requests.length} 个。`
        : "收尾完成，这轮问题清空了。", false);
    }

    async function send() {
      if (state.isSending) return;
      const responseType = typeSelect?.value || "text";
      const hasText = Boolean(textarea.value.trim());
      if (isSegmentedReply && responseType === "text" && !hasText && !streamChunks.length) {
        toast("我知道你很急，但第一下空回车只算清嗓子。先说一段。", false);
        textarea.focus();
        return;
      }
      if (!isSegmentedReply && responseType === "text" && !hasText) {
        toast("请先输入一段内容再发送。", true);
        textarea.focus();
        return;
      }
      state.isSending = true;
      submit.disabled = true;
      try {
        if (isSegmentedReply && responseType === "text") {
          if (hasText) {
            const chunk = await api(
              `/admin/api/requests/${encodeURIComponent(item.id)}/stream/chunks`,
              { method: "POST", body: { content: textarea.value, operator_id: state.operatorId } }
            );
            streamChunks.push(chunk);
            item.expires_at = chunk.expires_at;
            item.stream_chunk_count = streamChunks.length;
            const queuedItem = state.requests.find((request) => request.id === item.id);
            if (queuedItem) {
              queuedItem.stream_chunk_count = streamChunks.length;
              queuedItem.auto_reply_due_at = null;
            }
            composer.closest(".detail-shell")?.querySelector(".auto-countdown")?.remove();
            textarea.value = "";
            saveDraft(item.id, "");
            renderStreamLedger();
            updateDraftStatus();
            renderRequestList();
            toast(isRealtimeStream
              ? `第 ${chunk.position} 段已流出去。继续写，空回车才收尾。`
              : `第 ${chunk.position} 个 chunk 已生成。调用方会在空回车收尾后拿到全文。`, false);
            textarea.focus();
            return;
          }
          await api(
            `/admin/api/requests/${encodeURIComponent(item.id)}/stream/finish`,
            { method: "POST", body: { operator_id: state.operatorId } }
          );
          await advanceQueue();
          return;
        }

        const payload = { response_type: responseType, text: textarea.value, operator_id: state.operatorId };
        if (payload.response_type === "tool_call") {
          payload.tool_name = toolName.value;
          try { payload.tool_arguments = JSON.parse(toolArguments.value); }
          catch { throw new Error("工具参数必须是有效的 JSON 对象"); }
        }
        await api(`/admin/api/requests/${encodeURIComponent(item.id)}/answer`, { method: "POST", body: payload });
        await advanceQueue();
      } catch (error) {
        toast(error.message, true);
      } finally {
        submit.disabled = false;
        state.isSending = false;
      }
    }
    composer.addEventListener("submit", (event) => { event.preventDefault(); send(); });
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        send();
      }
    });
    return composer;
  }

  async function runRulePreview(text) {
    const result = $("#rule-preview-result");
    result.hidden = false;
    result.className = "rule-preview-result loading";
    result.replaceChildren(make("span", "", "正在让规则假装工作……"));
    try {
      const preview = await api("/admin/api/auto-rules/preview", {
        method: "POST",
        body: { text },
      });
      result.className = `rule-preview-result ${preview.matched ? "matched" : "clear"}`;
      if (!preview.matched) {
        result.replaceChildren(
          make("strong", "", "✓ 没有规则抢答"),
          make("p", "", preview.message)
        );
        return;
      }
      result.replaceChildren(
        make("strong", "", `⚡ ${preview.message}`),
        make("p", "", `命中原因：${preview.reason}`),
        make("blockquote", "", preview.rule.response_text)
      );
    } catch (error) {
      result.className = "rule-preview-result error";
      result.replaceChildren(make("strong", "", error.message));
    }
  }

  async function loadAutomation() {
    try {
      const [quickData, ruleData] = await Promise.all([
        api("/admin/api/quick-replies"),
        api("/admin/api/auto-rules"),
      ]);
      state.quickReplies = quickData.items;
      state.rules = ruleData.items;
      renderQuickReplies();
      renderRules();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderQuickReplies() {
    const list = $("#quick-reply-list");
    list.replaceChildren();
    state.quickReplies.forEach((reply) => {
      const card = make("article", `automation-item${reply.active ? "" : " inactive"}`);
      const head = make("div", "automation-item-head");
      const title = make("div");
      title.append(make("h4", "", reply.title), make("span", "item-meta", reply.category));
      const actions = make("div", "item-actions");
      const edit = make("button", "", "编辑"); edit.type = "button";
      edit.addEventListener("click", () => openQuickDialog(reply));
      const remove = make("button", "danger-action", "删除"); remove.type = "button";
      remove.addEventListener("click", () => deleteQuickReply(reply));
      actions.append(edit, remove);
      head.append(title, actions);
      card.append(head, make("p", "", reply.content));
      list.append(card);
    });
  }

  function renderRules() {
    const list = $("#auto-rule-list");
    list.replaceChildren();
    state.rules.forEach((rule) => {
      const card = make("article", `automation-item${rule.active ? "" : " inactive"}`);
      const head = make("div", "automation-item-head");
      const title = make("div");
      const trigger = rule.rule_type === "keyword"
        ? `${rule.match_type === "exact" ? "完全匹配" : "包含"}「${rule.pattern}」`
        : `${rule.start_time}–${rule.end_time} · ${rule.days.length} 天/周`;
      title.append(make("h4", "", rule.name), make("span", "item-meta", `${trigger} · 延迟 ${rule.delay_seconds}s`));
      const actions = make("div", "item-actions");
      const toggleLabel = make("label", "mini-switch");
      const toggle = make("input"); toggle.type = "checkbox"; toggle.checked = rule.active;
      toggle.addEventListener("change", () => toggleRule(rule, toggle));
      toggleLabel.append(toggle, make("i"));
      const edit = make("button", "", "编辑"); edit.type = "button"; edit.addEventListener("click", () => openRuleDialog(rule));
      const remove = make("button", "danger-action", "删除"); remove.type = "button"; remove.addEventListener("click", () => deleteRule(rule));
      actions.append(toggleLabel, edit, remove);
      head.append(title, actions);
      card.append(head, make("p", "", rule.response_text));
      list.append(card);
    });
  }

  function openQuickDialog(reply = null) {
    const form = $("#quick-form");
    form.reset();
    form.elements.id.value = reply?.id || "";
    form.elements.title.value = reply?.title || "";
    form.elements.category.value = reply?.category || "常用";
    form.elements.content.value = reply?.content || "";
    form.elements.active.checked = reply?.active ?? true;
    $("#quick-dialog-title").textContent = reply ? "编辑快捷话术" : "新建快捷话术";
    $("#quick-dialog").showModal();
  }

  async function deleteQuickReply(reply) {
    if (!confirm(`删除「${reply.title}」？这次是真的删。`)) return;
    try {
      await api(`/admin/api/quick-replies/${encodeURIComponent(reply.id)}`, { method: "DELETE" });
      toast("快捷话术已删除。少说一句，也是一种表达。", false);
      await loadAutomation();
    } catch (error) { toast(error.message, true); }
  }

  async function toggleRule(rule, input) {
    input.disabled = true;
    try {
      await api(`/admin/api/auto-rules/${encodeURIComponent(rule.id)}`, { method: "PATCH", body: { active: input.checked } });
      toast(input.checked ? `「${rule.name}」已上岗` : `「${rule.name}」已下班`, false);
      await Promise.all([loadAutomation(), loadOverview()]);
    } catch (error) { input.checked = !input.checked; toast(error.message, true); }
    finally { input.disabled = false; }
  }

  function openRuleDialog(rule = null) {
    const form = $("#rule-form");
    form.reset();
    form.elements.id.value = rule?.id || "";
    form.elements.name.value = rule?.name || "";
    form.elements.rule_type.value = rule?.rule_type || "keyword";
    form.elements.match_type.value = rule?.match_type || "contains";
    form.elements.pattern.value = rule?.pattern || "";
    form.elements.response_text.value = rule?.response_text || "";
    form.elements.start_time.value = rule?.start_time || "00:00";
    form.elements.end_time.value = rule?.end_time || "08:30";
    form.elements.delay_seconds.value = rule?.delay_seconds ?? 5;
    form.elements.priority.value = rule?.priority ?? 0;
    form.elements.active.checked = rule?.active ?? false;
    const days = rule?.days || [0, 1, 2, 3, 4, 5, 6];
    $$('input[name="days"]', form).forEach((input) => { input.checked = days.includes(Number(input.value)); });
    $("#rule-dialog-title").textContent = rule ? "编辑自动规则" : "新建自动规则";
    syncRuleFields();
    $("#rule-dialog").showModal();
  }

  async function deleteRule(rule) {
    if (!confirm(`删除自动规则「${rule.name}」？`)) return;
    try {
      await api(`/admin/api/auto-rules/${encodeURIComponent(rule.id)}`, { method: "DELETE" });
      toast("自动规则已拆除，控制权归还给肉身。", false);
      await Promise.all([loadAutomation(), loadOverview()]);
    } catch (error) { toast(error.message, true); }
  }

  function syncRuleFields() {
    const scheduled = $("#rule-form").elements.rule_type.value === "schedule";
    $("#keyword-rule-fields").hidden = scheduled;
    $("#schedule-rule-fields").hidden = !scheduled;
  }

  function renderIntegration(protocol = null) {
    const root = location.origin;
    const openaiBase = `${root}/v1`;
    const model = document.querySelector(".admin-console")?.dataset.modelName || "your-model";
    const activeButton = protocol
      ? $(`[data-integration-protocol="${protocol}"]`)
      : $("[data-integration-protocol].active");
    const selected = protocol || activeButton?.dataset.integrationProtocol || "openai";
    const examples = {
      openai: {
        language: "PYTHON · OPENAI",
        title: "OpenAI SDK",
        code: `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${openaiBase}",\n    api_key="sk-your-api-key",\n)\n\nresponse = client.responses.create(\n    model="${model}",\n    input="Hello from the OpenAI SDK",\n)\nprint(response.output_text)`,
      },
      claude: {
        language: "SHELL · CLAUDE CODE",
        title: "Claude Code",
        code: `export ANTHROPIC_BASE_URL="${root}"\nexport ANTHROPIC_AUTH_TOKEN="sk-your-api-key"\n\n# 从同一个终端启动，让 Claude Code 继承配置\nclaude\n\n# 进入后运行 /status，确认 Anthropic base URL`,
      },
      gemini: {
        language: "PYTHON · GOOGLE GENAI",
        title: "Google Gemini",
        code: `from google import genai\nfrom google.genai import types\n\nclient = genai.Client(\n    api_key="sk-your-api-key",\n    http_options=types.HttpOptions(\n        base_url="${root}",\n        api_version="v1beta",\n    ),\n)\n\nresponse = client.models.generate_content(\n    model="gemini-compatible",\n    contents="Hello from Gemini",\n)\nprint(response.text)`,
      },
      curl: {
        language: "SHELL · REST",
        title: "cURL / Responses API",
        code: `curl ${openaiBase}/responses \\\n  -H "Authorization: Bearer sk-your-api-key" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "model": "${model}",\n    "input": "Hello from curl"\n  }'`,
      },
    };
    const example = examples[selected] || examples.openai;
    $("#overview-api-base").textContent = openaiBase;
    $("#integration-root").textContent = root;
    $("#integration-openai-base").textContent = openaiBase;
    $("#integration-model").textContent = model;
    $("#integration-language").textContent = example.language;
    $("#integration-title").textContent = example.title;
    $("#integration-code").textContent = example.code;
    $$('[data-integration-protocol]').forEach((button) => {
      button.classList.toggle("active", button.dataset.integrationProtocol === selected);
    });
  }

  function preferredPublicRoot() {
    const configured = root.dataset.publicBaseUrl?.trim();
    return (configured || location.origin).replace(/\/+$/, "");
  }

  function shareCardData() {
    if (!state.lastCreatedKey) return null;
    const baseInput = $("#share-card-base-input");
    const base = (baseInput.value.trim() || preferredPublicRoot()).replace(/\/+$/, "");
    const item = state.lastCreatedKey.item;
    return {
      name: item.name,
      key: state.lastCreatedKey.key,
      model: root.dataset.modelName || "your-model",
      root: base,
      openaiBase: `${base}/v1`,
      limits: `每分钟 ${item.rate_limit_per_minute} 次 · 每日 ${item.daily_limit} 次 · 同时等待 ${item.max_concurrent} 个`,
    };
  }

  function renderShareCard() {
    const data = shareCardData();
    if (!data) return;
    $("#share-card-name").textContent = data.name;
    $("#share-card-openai-base").textContent = data.openaiBase;
    $("#share-card-root").textContent = data.root;
    $("#new-api-key-secret").textContent = data.key;
    $("#share-card-model").textContent = data.model;
    $("#share-card-limits").textContent = data.limits;
  }

  function openShareCard(result) {
    state.lastCreatedKey = result;
    $("#share-card-base-input").value = preferredPublicRoot();
    renderShareCard();
    $("#api-key-reveal-dialog").showModal();
  }

  function drawRoundedRect(context, x, y, width, height, radius, fill, stroke = null) {
    const r = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + r, y);
    context.lineTo(x + width - r, y);
    context.quadraticCurveTo(x + width, y, x + width, y + r);
    context.lineTo(x + width, y + height - r);
    context.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    context.lineTo(x + r, y + height);
    context.quadraticCurveTo(x, y + height, x, y + height - r);
    context.lineTo(x, y + r);
    context.quadraticCurveTo(x, y, x + r, y);
    context.closePath();
    if (fill) { context.fillStyle = fill; context.fill(); }
    if (stroke) { context.strokeStyle = stroke; context.lineWidth = 2; context.stroke(); }
  }

  function fitCanvasText(context, value, maxWidth, preferredSize, minimumSize = 22, family = '"SFMono-Regular", Menlo, monospace') {
    let size = preferredSize;
    while (size > minimumSize) {
      context.font = `600 ${size}px ${family}`;
      if (context.measureText(value).width <= maxWidth) break;
      size -= 2;
    }
    return size;
  }

  function createShareCardCanvas(data) {
    const canvas = document.createElement("canvas");
    canvas.width = 1600;
    canvas.height = 1000;
    const context = canvas.getContext("2d");
    const gradient = context.createLinearGradient(0, 0, 1600, 1000);
    gradient.addColorStop(0, "#111522");
    gradient.addColorStop(1, "#1b2140");
    context.fillStyle = gradient;
    context.fillRect(0, 0, canvas.width, canvas.height);

    context.globalAlpha = 0.18;
    context.fillStyle = "#7c86ff";
    context.beginPath(); context.arc(1470, 90, 330, 0, Math.PI * 2); context.fill();
    context.fillStyle = "#66d6a8";
    context.beginPath(); context.arc(80, 1030, 300, 0, Math.PI * 2); context.fill();
    context.globalAlpha = 1;

    drawRoundedRect(context, 78, 70, 62, 62, 18, "#cfd4ff");
    context.fillStyle = "#20284f";
    context.font = '800 34px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.textAlign = "center";
    context.fillText("I", 109, 112);
    context.textAlign = "left";
    context.fillStyle = "#ffffff";
    context.font = '750 32px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("iamllm", 160, 99);
    context.fillStyle = "#929bbf";
    context.font = '700 16px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("API ACCESS PASS", 160, 126);
    context.textAlign = "right";
    context.fillStyle = "#abb3d8";
    context.font = '700 18px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("OPENAI  ·  CLAUDE  ·  GEMINI", 1520, 108);
    context.textAlign = "left";

    context.fillStyle = "#7f89b1";
    context.font = '800 17px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("ACCESS FOR", 80, 218);
    context.fillStyle = "#ffffff";
    fitCanvasText(context, data.name, 1360, 70, 42, '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif');
    context.fillText(data.name, 80, 292);
    context.fillStyle = "#a7afcc";
    context.font = '400 24px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("一把钥匙，接入你已经在用的客户端。", 80, 337);

    const drawValueCard = (x, y, width, height, label, value, accent = false) => {
      drawRoundedRect(context, x, y, width, height, 24, accent ? "#252d57" : "rgba(255,255,255,.055)", accent ? "#515d9d" : "rgba(255,255,255,.11)");
      context.fillStyle = accent ? "#9ea9ff" : "#8992b3";
      context.font = '800 16px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
      context.fillText(label, x + 28, y + 40);
      context.fillStyle = "#f2f4ff";
      fitCanvasText(context, value, width - 56, accent ? 34 : 30, 20);
      context.fillText(value, x + 28, y + 92);
    };
    drawValueCard(80, 390, 700, 132, "OPENAI BASE URL", data.openaiBase);
    drawValueCard(820, 390, 700, 132, "CLAUDE / GEMINI BASE", data.root);
    drawValueCard(80, 552, 1440, 146, "API KEY", data.key, true);
    drawValueCard(80, 728, 700, 132, "MODEL", data.model);
    drawValueCard(820, 728, 700, 132, "LIMITS", data.limits);

    context.fillStyle = "#939bb9";
    context.font = '500 18px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("Authorization: Bearer API_KEY  ·  x-api-key: API_KEY  ·  x-goog-api-key: API_KEY", 80, 928);
    context.textAlign = "right";
    context.fillStyle = "#f1c88f";
    context.font = '700 18px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillText("包含完整 API Key，请私下分享", 1520, 928);
    return canvas;
  }

  async function downloadShareCard() {
    const data = shareCardData();
    if (!data) return;
    const button = $("#download-share-card");
    button.disabled = true;
    try {
      const canvas = createShareCardCanvas(data);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("浏览器没有生成图片，请重试");
      const link = document.createElement("a");
      const safeName = data.name.replace(/[^\w\u4e00-\u9fff-]+/g, "-").replace(/^-|-$/g, "") || "access";
      const objectUrl = URL.createObjectURL(blob);
      link.href = objectUrl;
      link.download = `iamllm-${safeName}-接入卡.png`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      toast("接入卡 PNG 已下载，请私下发送", false);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function copyShareCardText() {
    const data = shareCardData();
    if (!data) return;
    await copyText(
      `${data.name} · API 接入信息\n\nOpenAI Base URL: ${data.openaiBase}\nClaude / Gemini Base: ${data.root}\nAPI Key: ${data.key}\nModel: ${data.model}\nLimits: ${data.limits}\n\n此信息包含完整 API Key，请勿公开转发。`,
      "完整接入信息已复制"
    );
  }

  async function loadApiKeys() {
    const list = $("#api-key-list");
    list.setAttribute("aria-busy", "true");
    try {
      const data = await api("/admin/api/api-keys");
      state.apiKeys = data.items;
      renderApiKeys();
    } catch (error) {
      list.replaceChildren(make("div", "panel-loading", error.message));
    } finally {
      list.removeAttribute("aria-busy");
    }
  }

  function renderApiKeys() {
    const list = $("#api-key-list");
    list.replaceChildren();
    const active = state.apiKeys.filter((item) => item.active && !item.revoked).length;
    const today = state.apiKeys.reduce((sum, item) => sum + Number(item.usage_today || 0), 0);
    const pending = state.apiKeys.reduce((sum, item) => sum + Number(item.pending_requests || 0), 0);
    $("#key-active-count").textContent = active;
    $("#key-usage-today").textContent = today;
    $("#key-pending-count").textContent = pending;

    state.apiKeys.forEach((item) => {
      const card = make("article", `api-key-card key-${item.status}${item.managed ? "" : " key-master"}`);
      const head = make("div", "api-key-card-head");
      const identity = make("div");
      const title = make("div", "api-key-title");
      title.append(
        make("h3", "", item.name),
        make("span", `key-status key-status-${item.status}`, {
          active: item.managed ? "可调用" : "总钥匙",
          paused: "已暂停",
          revoked: "已撤销",
        }[item.status])
      );
      identity.append(title, make("code", "api-key-hint", item.key_hint));
      head.append(identity);

      const actions = make("div", "api-key-actions");
      if (item.managed && !item.revoked) {
        const toggle = make("button", "soft-action", item.active ? "暂停" : "恢复");
        toggle.type = "button";
        toggle.addEventListener("click", () => toggleApiKey(item));
        const edit = make("button", "soft-action", "调整额度");
        edit.type = "button";
        edit.addEventListener("click", () => openApiKeyDialog(item));
        const revoke = make("button", "danger-action", "永久撤销");
        revoke.type = "button";
        revoke.addEventListener("click", () => revokeApiKey(item));
        actions.append(toggle, edit, revoke);
      } else if (!item.managed) {
        actions.append(make("span", "key-readonly", "由部署环境保管"));
      }
      head.append(actions);
      card.append(head);

      const metrics = make("dl", "api-key-metrics");
      const values = item.unlimited
        ? [["分钟额度", "不限"], ["今日调用", "不统计"], ["同时等待", "不限"], ["最后出现", "随时可能"]]
        : [
          ["分钟额度", `${item.usage_minute} / ${item.rate_limit_per_minute}`],
          ["今日调用", `${item.usage_today} / ${item.daily_limit}`],
          ["同时等待", `${item.pending_requests} / ${item.max_concurrent}`],
          ["最后调用", item.last_used_at ? formatTime(item.last_used_at) : "还没用过"],
        ];
      values.forEach(([label, value]) => {
        const metric = make("div");
        metric.append(make("dt", "", label), make("dd", "", value));
        metrics.append(metric);
      });
      card.append(metrics);
      if (item.revoked) {
        card.append(make("p", "key-card-note", `这把钥匙已于 ${formatTime(item.revoked_at)} 永久退役。`));
      } else if (!item.managed) {
        card.append(make("p", "key-card-note", "它能打开所有门，也没有限速。别把总钥匙塞进公开仓库。"));
      }
      list.append(card);
    });
  }

  function openApiKeyDialog(item = null) {
    const form = $("#api-key-form");
    form.reset();
    form.elements.id.value = item?.id || "";
    form.elements.name.value = item?.name || "";
    form.elements.rate_limit_per_minute.value = item?.rate_limit_per_minute ?? 10;
    form.elements.daily_limit.value = item?.daily_limit ?? 100;
    form.elements.max_concurrent.value = item?.max_concurrent ?? 3;
    form.elements.active.checked = item?.active ?? true;
    $("#api-key-active-row").hidden = !item;
    $("#api-key-dialog-title").textContent = item ? `调整「${item.name}」` : "生成访问密钥";
    $("#api-key-submit").textContent = item ? "保存设置" : "生成密钥";
    $("#api-key-dialog").showModal();
  }

  async function toggleApiKey(item) {
    try {
      await api(`/admin/api/api-keys/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: { active: !item.active },
      });
      toast(item.active ? "密钥已暂停，客户端会收到 401" : "密钥已恢复", false);
      await loadApiKeys();
    } catch (error) { toast(error.message, true); }
  }

  async function revokeApiKey(item) {
    if (!confirm(`永久撤销「${item.name}」？撤销后不能恢复，复制过的钥匙也会立刻失效。`)) return;
    try {
      await api(`/admin/api/api-keys/${encodeURIComponent(item.id)}/revoke`, { method: "POST" });
      toast("钥匙已永久撤销。门还在，但这把钥匙已经变成纪念品。", false);
      await loadApiKeys();
    } catch (error) { toast(error.message, true); }
  }

  function populateProfile(profile) {
    const form = $("#profile-form");
    form.elements.display_name.value = profile.display_name;
    form.elements.bio.value = profile.bio;
    form.elements.availability.value = profile.availability;
    renderProfilePreview();
  }

  function renderServiceSettings() {
    populateProfile(state.profile);
    $("#settings-api-base").textContent = `${preferredPublicRoot()}/v1`;
  }

  function renderProfilePreview() {
    const form = $("#profile-form");
    const name = form.elements.display_name.value.trim() || "未命名模型";
    $("#preview-avatar").textContent = [...name][0] || "人";
    $("#preview-name").textContent = name;
    $("#preview-availability").textContent = form.elements.availability.value.trim() || "未设置状态说明";
  }

  async function saveProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("button[type='submit']", form);
    button.disabled = true;
    try {
      const data = await api("/admin/api/profile", {
        method: "PUT",
        body: {
          display_name: form.elements.display_name.value.trim(),
          bio: form.elements.bio.value.trim(),
          availability: form.elements.availability.value.trim(),
          skills: state.profile?.skills || [],
        },
      });
      state.profile = data;
      $("#profile-status").textContent = "已同步到 Playground 与 /v1/models";
      toast("服务展示设置已保存。", false);
      await loadOverview();
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  }

  function syncRequestFilterButtons() {
    $$("#request-filters button[data-filter]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filter === state.requestFilter);
    });
  }

  function switchRequestFilter(filter) {
    if (state.claimedRequestId) {
      const claimed = state.claimedRequestId;
      state.claimedRequestId = null;
      releaseClaim(claimed);
    }
    state.requestFilter = filter;
    state.selectedRequestId = null;
    state.selectedRequestStatus = null;
    state.selectedRequestDetail = null;
    state.queueJustCleared = false;
    state.queueLoaded = false;
    state.knownRequestIds = new Set();
    state.newArrivalIds = new Set();
    history.replaceState(null, "", "#inbox");
    syncRequestFilterButtons();
    $("#new-request-notice").hidden = true;
    return loadRequests({ reason: "filter", forceDetail: true });
  }

  function bindEvents() {
    $$(".console-nav button[data-section]").forEach((button) => button.addEventListener("click", () => { location.hash = `#${button.dataset.section}`; }));
    $$('[data-integration-protocol]').forEach((button) => {
      button.addEventListener("click", () => renderIntegration(button.dataset.integrationProtocol));
    });
    $$('[data-copy-target]').forEach((button) => {
      button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.copyTarget);
        if (target) copyText(target.textContent.trim(), "已复制到剪贴板");
      });
    });
    $("#test-notification").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await api("/admin/api/notifications/test", { method: "POST" });
        toast("测试通知已出发。去看看它有没有敲你。", false);
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = !state.overview?.notifications_enabled;
      }
    });
    $$('[data-go]').forEach((button) => button.addEventListener("click", () => { location.hash = `#${button.dataset.go}`; }));
    $("#request-filters").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-filter]");
      if (!button) return;
      switchRequestFilter(button.dataset.filter);
    });
    const autoOpen = $("#auto-open-requests");
    autoOpen.checked = state.autoOpen;
    autoOpen.addEventListener("change", () => {
      state.autoOpen = autoOpen.checked;
      try { localStorage.setItem("iamllm_auto_open", state.autoOpen ? "on" : "off"); }
      catch { /* The toggle still works for this session. */ }
      toast(state.autoOpen ? "空闲自动接单已开启" : "空闲自动接单已关闭，新问题只进队列", false);
    });
    $("#new-request-notice").addEventListener("click", () => {
      const target = state.requests.find((item) => state.newArrivalIds.has(item.id)) || state.requests[0];
      if (target) selectRequest(target.id, true, { focusComposer: true });
    });
    $("#new-quick").addEventListener("click", () => openQuickDialog());
    $("#new-rule").addEventListener("click", () => openRuleDialog());
    $("#new-api-key").addEventListener("click", () => openApiKeyDialog());
    $("#rule-preview-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = event.currentTarget.elements.text.value.trim();
      if (text) runRulePreview(text);
    });
    $$('[data-dialog-close]').forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
    $("#rule-form").elements.rule_type.addEventListener("change", syncRuleFields);
    $("#profile-form").addEventListener("input", renderProfilePreview);
    $("#profile-form").addEventListener("submit", saveProfile);
    document.addEventListener("keydown", (event) => {
      if (currentRoute().section !== "inbox" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable) return;
      if (event.key.toLowerCase() === "j") { event.preventDefault(); cycleRequest(1); }
      if (event.key.toLowerCase() === "k") { event.preventDefault(); cycleRequest(-1); }
    });

    $("#quick-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const id = form.elements.id.value;
      const body = {
        title: form.elements.title.value.trim(),
        category: form.elements.category.value.trim(),
        content: form.elements.content.value.trim(),
        active: form.elements.active.checked,
      };
      try {
        await api(id ? `/admin/api/quick-replies/${encodeURIComponent(id)}` : "/admin/api/quick-replies", { method: id ? "PATCH" : "POST", body });
        $("#quick-dialog").close();
        toast(id ? "快捷话术已更新" : "快捷话术已加入弹药库", false);
        await loadAutomation();
      } catch (error) { toast(error.message, true); }
    });

    $("#rule-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const id = form.elements.id.value;
      const body = {
        name: form.elements.name.value.trim(),
        rule_type: form.elements.rule_type.value,
        match_type: form.elements.match_type.value,
        pattern: form.elements.pattern.value.trim() || null,
        response_text: form.elements.response_text.value.trim(),
        start_time: form.elements.start_time.value || null,
        end_time: form.elements.end_time.value || null,
        days: $$('input[name="days"]:checked', form).map((input) => Number(input.value)),
        delay_seconds: Number(form.elements.delay_seconds.value),
        priority: Number(form.elements.priority.value),
        active: form.elements.active.checked,
      };
      try {
        await api(id ? `/admin/api/auto-rules/${encodeURIComponent(id)}` : "/admin/api/auto-rules", { method: id ? "PATCH" : "POST", body });
        $("#rule-dialog").close();
        toast(id ? "自动规则已更新" : "自动规则已创建，方向盘还在你手里", false);
        await Promise.all([loadAutomation(), loadOverview()]);
      } catch (error) { toast(error.message, true); }
    });

    $("#api-key-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const id = form.elements.id.value;
      const body = {
        name: form.elements.name.value.trim(),
        rate_limit_per_minute: Number(form.elements.rate_limit_per_minute.value),
        daily_limit: Number(form.elements.daily_limit.value),
        max_concurrent: Number(form.elements.max_concurrent.value),
      };
      if (id) body.active = form.elements.active.checked;
      const submit = $("#api-key-submit");
      submit.disabled = true;
      try {
        const result = await api(
          id ? `/admin/api/api-keys/${encodeURIComponent(id)}` : "/admin/api/api-keys",
          { method: id ? "PATCH" : "POST", body }
        );
        $("#api-key-dialog").close();
        if (!id) {
          openShareCard(result);
        } else {
          toast("钥匙设置已保存，限速器重新校准。", false);
        }
        await loadApiKeys();
      } catch (error) { toast(error.message, true); }
      finally { submit.disabled = false; }
    });

    $("#copy-api-key").addEventListener("click", async () => {
      const secret = state.lastCreatedKey?.key || "";
      if (!secret) return;
      await copyText(secret, "API Key 已复制，请妥善保存");
    });
    $("#copy-share-card-text").addEventListener("click", copyShareCardText);
    $("#download-share-card").addEventListener("click", downloadShareCard);
    $("#share-card-base-input").addEventListener("input", renderShareCard);
    $("#api-key-reveal-dialog").addEventListener("close", () => {
      state.lastCreatedKey = null;
      $("#new-api-key-secret").textContent = "—";
    });

    window.addEventListener("hashchange", () => showSection(currentRoute().section));
  }

  function buildWeekdayPicker() {
    const picker = $("#weekday-picker");
    ["一", "二", "三", "四", "五", "六", "日"].forEach((label, index) => {
      const day = make("label");
      const input = make("input"); input.type = "checkbox"; input.name = "days"; input.value = index; input.checked = true;
      day.append(input, make("span", "", label));
      picker.append(day);
    });
  }

  async function refreshSelectedPresence() {
    if (!state.selectedRequestId || state.selectedRequestStatus !== "pending") return;
    try {
      const presence = await api(
        `/admin/api/requests/${encodeURIComponent(state.selectedRequestId)}/presence`
      );
      const item = state.requests.find((request) => request.id === state.selectedRequestId);
      if (item) Object.assign(item, presence);
      const badge = $("#request-presence");
      if (badge) {
        badge.classList.toggle("online", presence.client_connected);
        badge.classList.toggle("offline", !presence.client_connected);
        badge.textContent = presence.client_connected
          ? "● 客户端在线 · 你发出的 chunk 会立即送达"
          : presence.client_last_seen_at
            ? "○ 客户端可能已断开 · 响应仍会保存并可稍后查询"
            : "○ 暂时没收到客户端心跳 · API 调用方可能正在轮询";
      }
      const ownedElsewhere = presence.claim_active && presence.claim_owner !== state.operatorId;
      if (ownedElsewhere && !state.selectedRequestClaimConflict) {
        state.claimedRequestId = null;
        await selectRequest(state.selectedRequestId, false, { force: true });
      }
    } catch { /* Presence is advisory; the main queue sync handles hard errors. */ }
  }

  async function renewSelectedClaim() {
    if (!state.claimedRequestId || state.selectedRequestStatus !== "pending") return;
    try {
      await api(`/admin/api/requests/${encodeURIComponent(state.claimedRequestId)}/claim`, {
        method: "POST",
        body: { operator_id: state.operatorId },
      });
      state.claimRenewAt = Date.now() + 10_000;
    } catch (error) {
      if (error.status === 409) {
        state.claimedRequestId = null;
        await selectRequest(state.selectedRequestId, false, { force: true });
      }
    }
  }

  function startRealtimeSync() {
    const indicator = $("#live-status");
    let lastVersion = state.overview?.queue_version ?? null;
    let timer = null;
    let syncing = false;

    async function sync() {
      clearTimeout(timer);
      if (syncing) return;
      if (document.hidden) {
        timer = setTimeout(sync, 8_000);
        return;
      }
      syncing = true;
      const previousPending = state.overview?.pending || 0;
      const overview = await loadOverview({ silent: true });
      if (overview) {
        indicator.classList.remove("offline");
        indicator.lastChild.textContent = " 服务在线";
        if (lastVersion !== null && overview.queue_version !== lastVersion) {
          const route = currentRoute();
          if (route.section === "inbox") {
            if (state.isSending) state.queueRefreshPending = true;
            else await loadRequests({ reason: "realtime" });
          } else if (overview.pending > previousPending) {
            toast("有新问题到了，已经放进“等我回”。", false);
          }
          if (route.section === "automation") await loadAutomation();
        }
        lastVersion = overview.queue_version;
      } else {
        indicator.classList.add("offline");
        indicator.lastChild.textContent = " 正在重新连接";
      }
      if (Date.now() >= state.presenceRefreshAt) {
        state.presenceRefreshAt = Date.now() + 3_000;
        await refreshSelectedPresence();
      }
      if (Date.now() >= state.claimRenewAt) await renewSelectedClaim();
      syncing = false;
      timer = setTimeout(sync, 1_200);
    }

    document.addEventListener("visibilitychange", () => {
      clearTimeout(timer);
      if (!document.hidden) sync();
      else timer = setTimeout(sync, 8_000);
    });
    const deadlineTimer = setInterval(() => {
      $$('[data-stream-deadline="true"]').forEach(updateStreamDeadline);
    }, 1_000);
    window.addEventListener("pagehide", () => {
      clearTimeout(timer);
      clearInterval(deadlineTimer);
      if (state.claimedRequestId) releaseClaim(state.claimedRequestId, { beacon: true });
    });
    sync();
  }

  async function init() {
    buildWeekdayPicker();
    bindEvents();
    renderIntegration("openai");
    await Promise.all([loadOverview(), loadAutomation()]);
    renderServiceSettings();
    showSection(currentRoute().section);
    startRealtimeSync();
  }

  init();
})();
