import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Message, Part, QuickReply, RequestItem } from "../types";
import { compact, ConversationEmpty, Empty, Icon, PageHead, relative, sourceLabel, stateLabel, Toast } from "../ui";

export function InboxPage({ onPending }: { onPending: (n: number) => void }) {
  const [items, setItems] = useState<RequestItem[]>([]),
    [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<RequestItem | null>(null),
    [filter, setFilter] = useState("pending"),
    [search, setSearch] = useState(""),
    [notice, setNotice] = useState(""),
    [notificationPermission, setNotificationPermission] = useState<NotificationPermission | "unsupported">(
      typeof Notification === "undefined" ? "unsupported" : Notification.permission,
    );
  const busy = useRef(false);
  async function load(quiet = false) {
    if (busy.current) return;
    busy.current = true;
    try {
      const data = await api.request<{ items: RequestItem[]; total: number }>(
        `/admin/api/v1/requests?status=${filter}&limit=200`,
      );
      setItems(data.items);
      if (filter === "pending") onPending(data.total);
      if (!selected && data.items[0]) setSelected(data.items[0].id);
      if (
        selected &&
        !data.items.some((x) => x.id === selected) &&
        data.items[0]
      )
        setSelected(data.items[0].id);
    } catch (e) {
      if (!quiet) setNotice(e instanceof Error ? e.message : "加载失败");
    } finally {
      busy.current = false;
    }
  }
  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), 5000);
    return () => clearInterval(timer);
  }, [filter]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const listed = items.find((item) => item.id === selected);
    if (listed && !listed.read_at) {
      const readAt = Date.now();
      setItems((current) => current.map((item) => item.id === selected ? { ...item, read_at: readAt } : item));
      api.request<RequestItem>(`/admin/api/v1/requests/${selected}/read`, {
        method: "PUT",
        body: "{}",
      }).catch(() => {});
    }
    api
      .request<RequestItem>(`/admin/api/v1/requests/${selected}`)
      .then(setDetail)
      .catch((e) => setNotice(e.message));
  }, [selected]);
  useEffect(() => {
    let closed = false;
    const controller = new AbortController();
    (async () => {
      let lastEventID = sessionStorage.getItem("iamllm.last-event-id") || "";
      while (!closed) {
        try {
          const headers: Record<string, string> = {
            Authorization: `Bearer ${api.access}`,
          };
          if (lastEventID) headers["Last-Event-ID"] = lastEventID;
          let response = await fetch("/admin/api/v1/events", {
            headers,
            signal: controller.signal,
          });
          if (response.status === 401 && api.refreshToken) {
            await api.refresh();
            headers.Authorization = `Bearer ${api.access}`;
            response = await fetch("/admin/api/v1/events", {
              headers,
              signal: controller.signal,
            });
          }
          if (!response.ok) throw new Error("事件连接失败");
          const reader = response.body?.getReader(),
            decoder = new TextDecoder();
          let buffer = "";
          while (reader && !closed) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split("\n\n");
            buffer = events.pop() || "";
            for (const event of events) {
              const lines = event.split("\n");
              const id = event
                .split("\n")
                .find((line) => line.startsWith("id:"))
                ?.slice(3)
                .trim();
              if (id) {
                lastEventID = id;
                sessionStorage.setItem("iamllm.last-event-id", id);
              }
              const eventType = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
              const data = lines.find((line) => line.startsWith("data:"))?.slice(5).trim();
              if (eventType === "request.created" && data && typeof Notification !== "undefined" && Notification.permission === "granted") {
                try {
                  const parsed = JSON.parse(data) as { resource_id?: string; payload?: { preview?: string; automated?: boolean } };
                  if (!parsed.payload?.automated && document.hidden) {
                    const alert = new Notification("有一条新消息", {
                      body: parsed.payload?.preview || "有人正在等你的回答",
                      tag: parsed.resource_id || "iamllm-request",
                    });
                    alert.onclick = () => {
                      window.focus();
                      setFilter("pending");
                      if (parsed.resource_id) setSelected(parsed.resource_id);
                      alert.close();
                    };
                  }
                } catch {}
              }
            }
            if (events.some((event) => event.includes("request."))) {
              await load(true);
              if (selected)
                api
                  .request<RequestItem>(`/admin/api/v1/requests/${selected}`)
                  .then(setDetail);
            }
          }
        } catch {
          if (!closed)
            await new Promise((resolve) => window.setTimeout(resolve, 1200));
        }
      }
    })();
    return () => {
      closed = true;
      controller.abort();
    };
  }, [selected, filter]);
  const unread = items.filter((item) => !item.read_at).length;
  useEffect(() => {
    document.title = unread > 0 ? `(${unread}) iamllm` : "iamllm";
    return () => { document.title = "iamllm"; };
  }, [unread]);
  async function enableNotifications() {
    if (typeof Notification === "undefined") {
      setNotice("当前浏览器不支持桌面提醒");
      return;
    }
    if (Notification.permission === "denied") {
      setNotice("浏览器已关闭提醒，请在网站设置里重新允许");
      return;
    }
    const permission = await Notification.requestPermission();
    setNotificationPermission(permission);
    setNotice(permission === "granted" ? "新消息提醒已打开" : "没有开启提醒，也不影响实时同步");
  }
  const visibleItems = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) =>
      [item.preview, sourceLabel(item.source), item.model]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }, [items, search]);
  return (
    <section className="page inboxPage">
      <PageHead
        eyebrow="CONVERSATION DESK"
        title="会话工作台"
        subtitle="一眼看清谁在等，专心完成当前这一个回答。"
      >
        <div className="headStatus">
          <span className="livePill"><i className="online" /> 实时同步中</span>
          <button className={`iconButton ${notificationPermission === "granted" ? "enabled" : ""}`} title={notificationPermission === "granted" ? "新消息提醒已开启" : "开启新消息提醒"} onClick={enableNotifications}><Icon name="bell" /></button>
          <button className="iconButton" title="刷新" onClick={() => load()}><Icon name="refresh" /></button>
        </div>
      </PageHead>
      {notice && <Toast text={notice} close={() => setNotice("")} />}
      <div className={`workbench ${selected ? "hasSelection" : ""}`}>
        <div className="queue">
          <div className="queueTop">
            <div className="segmented">
              {["pending", "answered", "expired"].map((x) => (
                <button
                  className={filter === x ? "on" : ""}
                  onClick={() => {
                    setFilter(x);
                    setSelected("");
                  }}
                  key={x}
                >
                  {x === "pending" ? "待回答" : x === "answered" ? "已回答" : "已过期"}
                  {filter === x && items.length > 0 && <em>{items.length}</em>}
                </button>
              ))}
            </div>
            <label className="queueSearch"><Icon name="search" size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索会话" /></label>
          </div>
          {visibleItems.length === 0 ? (
            <Empty search={Boolean(search)} />
          ) : (
            <div className="queueList">
            {visibleItems.map((item) => (
              <button
                className={`${selected === item.id ? "selected" : ""} ${!item.read_at ? "unread" : ""}`}
                onClick={() => setSelected(item.id)}
                key={item.id}
              >
                <span className="queueMeta">
                  <b><i className={`stateDot ${item.status}`} />{stateLabel(item)}</b>
                  <time>{relative(item.created_at)}</time>
                </span>
                <strong>{item.preview}</strong>
                {item.status === "pending" && item.draft && <p className="draftPreview"><b>草稿</b>{item.draft}</p>}
                <div className="chips">
                  <i>{sourceLabel(item.source)}</i>
                  {item.context_chars > 20000 && (
                    <i>{compact(item.context_chars)} 字符</i>
                  )}
                  {item.tool_count > 0 && <i>工具 {item.tool_count}</i>}
                  {item.attachment_count > 0 && (
                    <i>附件 {item.attachment_count}</i>
                  )}
                  <span className="queueArrow"><Icon name="chevron" size={15} /></span>
                </div>
              </button>
            ))}</div>
          )}
        </div>
        <div className="conversation">
          {detail ? (
            <Conversation
              item={detail}
              refresh={() =>
                api
                  .request<RequestItem>(`/admin/api/v1/requests/${detail.id}`)
                  .then(setDetail)
              }
              onDone={() => {
                setSelected("");
                load();
              }}
              notify={setNotice}
              onBack={() => setSelected("")}
            />
          ) : (
            <ConversationEmpty filter={filter} />
          )}
        </div>
      </div>
    </section>
  );
}
function Conversation({
  item,
  refresh,
  onDone,
  notify,
  onBack,
}: {
  item: RequestItem;
  refresh: () => void;
  onDone: () => void;
  notify: (s: string) => void;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<"chat" | "run" | "raw">("chat"),
    [raw, setRaw] = useState<Message[]>([]),
    [quickReplies, setQuickReplies] = useState<QuickReply[]>([]),
    [text, setText] = useState(""),
    [responseMode, setResponseMode] = useState<"text" | "tool">("text"),
    [toolName, setToolName] = useState(""),
    [toolArguments, setToolArguments] = useState("{}"),
    [sent, setSent] = useState(item.stream_chunk_count || 0),
    [busy, setBusy] = useState(false),
    [sendState, setSendState] = useState<"idle" | "sending" | "sent" | "failed">("idle"),
    [failedAction, setFailedAction] = useState<{ kind: "chunk" | "complete" | "direct"; content?: string } | null>(null),
    [optimisticChunk, setOptimisticChunk] = useState(""),
    [nearBottom, setNearBottom] = useState(true),
    [newBelow, setNewBelow] = useState(false),
    operator = useMemo(() => {
      let id = sessionStorage.getItem("iamllm.operator");
      if (!id) {
        id = crypto.randomUUID().replaceAll("-", "");
        sessionStorage.setItem("iamllm.operator", id);
      }
      return id;
    }, []),
    bottom = useRef<HTMLDivElement>(null),
    messageList = useRef<HTMLDivElement>(null),
    draftReady = useRef(false),
    lastSavedDraft = useRef(""),
    draftTimer = useRef<number | null>(null);

  function scrollToLatest(behavior: ScrollBehavior = "smooth") {
    bottom.current?.scrollIntoView({ behavior, block: "end" });
    setNearBottom(true);
    setNewBelow(false);
  }
  useEffect(() => {
    setSent(item.stream_chunk_count || 0);
    setRaw([]);
    setText(item.status === "pending" ? item.draft || "" : "");
    lastSavedDraft.current = item.draft || "";
    draftReady.current = true;
    setSendState("idle");
    setFailedAction(null);
    setOptimisticChunk("");
    setNearBottom(true);
    setNewBelow(false);
    requestAnimationFrame(() => scrollToLatest("auto"));
  }, [item.id]);
  useEffect(() => {
    setSent(item.stream_chunk_count || 0);
  }, [item.stream_chunk_count]);
  useEffect(() => {
    if (!draftReady.current || item.status !== "pending") return;
    if (item.draft_device_id && item.draft_device_id !== operator && text === lastSavedDraft.current) {
      const incoming = item.draft || "";
      lastSavedDraft.current = incoming;
      setText(incoming);
    }
  }, [item.draft_updated_at]);
  useEffect(() => {
    if (!draftReady.current || item.status !== "pending" || text === lastSavedDraft.current) return;
    if (draftTimer.current) window.clearTimeout(draftTimer.current);
    draftTimer.current = window.setTimeout(async () => {
      const value = text;
      lastSavedDraft.current = value;
      try {
        await api.request(`/admin/api/v1/requests/${item.id}/draft`, {
          method: "PUT",
          body: JSON.stringify({ content: value, device_id: operator }),
        });
      } catch {
        if (lastSavedDraft.current === value) lastSavedDraft.current = "\u0000";
      }
    }, 650);
    return () => {
      if (draftTimer.current) window.clearTimeout(draftTimer.current);
    };
  }, [text, item.id, item.status, operator]);
  useEffect(() => {
    if (tab !== "chat") return;
    if (nearBottom) requestAnimationFrame(() => scrollToLatest());
    else setNewBelow(true);
  }, [item.stream_chunk_count, optimisticChunk, item.messages?.length]);
  useEffect(() => {
    api
      .request<{ items: QuickReply[] }>("/admin/api/v1/quick-replies")
      .then((value) => setQuickReplies(value.items))
      .catch(() => {});
  }, []);
  async function choose(next: "chat" | "run" | "raw") {
    setTab(next);
    if (next === "raw" && raw.length === 0) {
      try {
        const value = await api.request<{ messages: Message[] }>(
          `/admin/api/v1/requests/${item.id}/raw`,
        );
        setRaw(value.messages || []);
      } catch (e) {
        notify(e instanceof Error ? e.message : "原始上下文加载失败");
      }
    }
  }
  async function chunk(retryContent?: string) {
    const value = (retryContent ?? text).trim();
    if (!value) {
      if (sent === 0) {
        notify("第一下空回车不会结束——模型只是眨了眨眼。");
        return;
      }
      await complete();
      return;
    }
    setBusy(true);
    setSendState("sending");
    setFailedAction(null);
    setOptimisticChunk(value);
    try {
      await api.request(`/admin/api/v1/requests/${item.id}/chunks`, {
        method: "POST",
        body: JSON.stringify({
          chunk_id: crypto.randomUUID(),
          content: value,
          operator_id: operator,
        }),
      });
      setText("");
      lastSavedDraft.current = "";
      setOptimisticChunk("");
      setSent((v) => v + 1);
      setSendState("sent");
      refresh();
    } catch (e) {
      setOptimisticChunk("");
      setSendState("failed");
      setFailedAction({ kind: "chunk", content: value });
    } finally {
      setBusy(false);
    }
  }
  async function complete() {
    setBusy(true);
    setSendState("sending");
    setFailedAction(null);
    try {
      await api.request(`/admin/api/v1/requests/${item.id}/complete`, {
        method: "POST",
        body: "{}",
      });
      setSendState("sent");
      onDone();
    } catch {
      setSendState("failed");
      setFailedAction({ kind: "complete" });
    } finally {
      setBusy(false);
    }
  }
  async function direct() {
    if (responseMode === "text" && !text.trim()) return;
    setBusy(true);
    setSendState("sending");
    setFailedAction(null);
    try {
      let body: Record<string, unknown> = {
        content: text,
        operator_id: operator,
      };
      if (responseMode === "tool") {
        let argumentsValue: Record<string, unknown>;
        try {
          argumentsValue = JSON.parse(toolArguments);
        } catch {
          throw new Error("工具参数需要是合法 JSON");
        }
        body = {
          response_type: "tool_call",
          tool_name: selectedTool,
          tool_arguments: argumentsValue,
          operator_id: operator,
        };
      }
      await api.request(`/admin/api/v1/requests/${item.id}/answer`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setSendState("sent");
      onDone();
    } catch {
      setSendState("failed");
      setFailedAction({ kind: "direct" });
    } finally {
      setBusy(false);
    }
  }
  async function retryFailed() {
    if (!failedAction) return;
    if (failedAction.kind === "chunk") await chunk(failedAction.content);
    else if (failedAction.kind === "complete") await complete();
    else await direct();
  }
  const messages =
    tab === "chat" ? item.messages || [] : tab === "raw" ? raw : [];
  const availableTools = (item.tools || [])
    .map((tool) => (tool as { function?: { name?: string } }).function?.name)
    .filter((name): name is string => Boolean(name));
  const selectedTool = toolName || availableTools[0] || "";
  const streamedReply = [...(item.stream_chunks || [])]
    .sort((a, b) => a.position - b.position)
    .map((chunk) => chunk.content)
    .join("");
  const visibleReply = item.status === "answered"
    ? item.answer || streamedReply
    : streamedReply + optimisticChunk;
  return (
    <>
      <header className="conversationHead">
        <button className="mobileBack" onClick={onBack}><Icon name="back" /> 会话</button>
        <div>
          <small><span className={`stateDot ${item.status}`} /> {sourceLabel(item.source)} · {relative(item.created_at)}</small>
          <h2>{item.preview}</h2>
        </div>
        <div className="tabs">
          <button
            className={tab === "chat" ? "on" : ""}
            onClick={() => choose("chat")}
          >
            <Icon name="message" size={15} />聊天
          </button>
          <button
            className={tab === "run" ? "on" : ""}
            onClick={() => choose("run")}
          >
            <Icon name="activity" size={15} />运行记录
          </button>
          <button
            className={tab === "raw" ? "on" : ""}
            onClick={() => choose("raw")}
          >
            <Icon name="raw" size={15} />原始上下文
          </button>
        </div>
      </header>
      <div className="messageStage">
      <div className="messages" ref={messageList} onScroll={() => {
        const node = messageList.current;
        if (!node) return;
        const close = node.scrollHeight - node.scrollTop - node.clientHeight < 96;
        setNearBottom(close);
        if (close) setNewBelow(false);
      }}>
        {tab === "run" ? (
          <RunView item={item} />
        ) : messages.length ? (
          messages.map((m, i) => <Bubble message={m} key={i} />)
        ) : (
          <div className="mutedBox">这一视图没有内容。</div>
        )}
        {tab === "chat" && visibleReply && (
          <div className={`bubble assistant streamedReply ${sendState === "failed" ? "failed" : ""}`}>
            <small>{item.status === "pending" ? `你的回复 · ${sendState === "sending" ? "发送中" : sendState === "failed" ? "发送失败" : "已送达"}` : "助手"}</small>
            <p>{visibleReply}</p>
          </div>
        )}
        <div ref={bottom} />
      </div>
      {newBelow && <button className="jumpToLatest" onClick={() => scrollToLatest()}>↓ 新消息</button>}
      </div>
      {item.status === "pending" && (
        <div className="composer">
          <div className={`live ${item.client_online ? "connected" : ""}`}>
            <span><i className={item.client_online ? "online" : "idle"} />
              <b>{item.client_online ? "客户端正在等待" : "客户端暂时离线"}</b>
              <small>{item.client_online ? "你发送的每一段都会实时抵达" : "回复会保存，重连后继续送达"}</small>
            </span>
            <em>{sent ? `已发送 ${sent} 段` : "尚未开始"}</em>
          </div>
          {quickReplies.length > 0 && (
            <div className="quickReplies">
              {quickReplies.map((reply) => (
                <button
                  key={reply.id}
                  onClick={() => {
                    setResponseMode("text");
                    setText(reply.content);
                  }}
                >
                  {reply.title}
                </button>
              ))}
            </div>
          )}
          {availableTools.length > 0 && sent === 0 && (
            <div className="replyMode">
              <button
                className={responseMode === "text" ? "on" : ""}
                onClick={() => setResponseMode("text")}
              >
                <Icon name="message" size={14} />文字回答
              </button>
              <button
                className={responseMode === "tool" ? "on" : ""}
                onClick={() => setResponseMode("tool")}
              >
                <Icon name="bolt" size={14} />调用客户端工具
              </button>
            </div>
          )}
          {responseMode === "tool" && availableTools.length > 0 ? (
            <div className="toolComposer">
              <label>
                工具
                <select
                  value={selectedTool}
                  onChange={(e) => setToolName(e.target.value)}
                >
                  {availableTools.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label>
                参数 JSON
                <textarea
                  value={toolArguments}
                  onChange={(e) => setToolArguments(e.target.value)}
                  placeholder='{"path":"README.md"}'
                />
              </label>
              <p>
                服务只把调用指令返回给客户端；工具会在 Codex、Claude Code 或
                OpenCode 那一端执行。
              </p>
            </div>
          ) : (
            <div className="composerInput">
              <textarea
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (sendState === "failed") {
                    setSendState("idle");
                    setFailedAction(null);
                  }
                }}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    chunk();
                  }
                }}
                placeholder={sent ? "继续写下一段，或空白 Enter 结束回答" : "像聊天一样写下第一段回复…"}
              />
              <span><kbd>Enter</kbd> 发送当前段 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行</span>
            </div>
          )}
          <div className="composerActions">
            <span className={`sendFeedback ${sendState}`}>
              {sendState === "sending" && "正在发送…"}
              {sendState === "sent" && "✓ 已送达"}
              {sendState === "failed" && <>发送失败 <button onClick={retryFailed}>重试</button></>}
            </span>
            <button
              className="ghost"
              onClick={direct}
              disabled={
                busy || sent > 0 || (responseMode === "tool" && !selectedTool)
              }
            >
              {responseMode === "tool" ? "返回工具调用" : "整段发送并结束"}
            </button>
            {responseMode === "text" && (
              <button className="primaryAction" onClick={() => chunk()} disabled={busy}>
                {text.trim() ? <>发送这一段 <Icon name="send" size={15} /></> : sent ? <>结束回答 <Icon name="check" size={15} /></> : "等待输入"}
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
function Bubble({ message }: { message: Message }) {
  const user = message.role === "user";
  return (
    <div className={`bubble ${user ? "user" : "assistant"}`}>
      <small>{user ? "用户" : "助手"}</small>
      {typeof message.content === "string" ? (
        <p>{message.content}</p>
      ) : Array.isArray(message.content) ? (
        message.content.map((p, i) => <PartView part={p} key={i} />)
      ) : (
        <p className="muted">空内容</p>
      )}
    </div>
  );
}
function PartView({ part }: { part: Part }) {
  if (part.type.includes("text")) return <p>{part.text}</p>;
  if (part.type.includes("image")) {
    const src =
      typeof part.image_url === "string" ? part.image_url : part.image_url?.url;
    return src ? (
      <SecureImage src={src} />
    ) : (
      <div className="fileCard">图片附件</div>
    );
  }
  if (part.type.includes("file") || part.type === "document")
    return (
      <div className="fileCard">
        <b>{part.file?.filename || "文件附件"}</b>
        <span>{part.file?.mime_type || "未知格式"}</span>
      </div>
    );
  return <pre>{JSON.stringify(part, null, 2)}</pre>;
}
function SecureImage({ src }: { src: string }) {
  const [value, setValue] = useState(src.startsWith("/admin/") ? "" : src);
  useEffect(() => {
    if (!src.startsWith("/admin/")) {
      setValue(src);
      return;
    }
    let active = true,
      objectURL = "";
    fetch(src, { headers: { Authorization: `Bearer ${api.access}` } })
      .then((r) => {
        if (!r.ok) throw new Error("图片加载失败");
        return r.blob();
      })
      .then((blob) => {
        if (active) {
          objectURL = URL.createObjectURL(blob);
          setValue(objectURL);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
      if (objectURL) URL.revokeObjectURL(objectURL);
    };
  }, [src]);
  return value ? (
    <img className="attachment" src={value} />
  ) : (
    <div className="fileCard">正在安全加载图片…</div>
  );
}
function RunView({ item }: { item: RequestItem }) {
  return (
    <div className="run">
      <div>
        <b>协议来源</b>
        <span>
          {sourceLabel(item.source)} · {item.model}
        </span>
      </div>
      <div>
        <b>上下文体积</b>
        <span>{item.context_chars.toLocaleString()} 字符</span>
      </div>
      <div>
        <b>工具定义 / 调用</b>
        <span>{item.tool_count} 项</span>
      </div>
      <div>
        <b>回复传输</b>
        <span>{item.stream_chunk_count > 0 ? `${item.stream_chunk_count} 个 chunk · 聊天中合并为一条` : "整段返回"}</span>
      </div>
      {item.stream_chunks && item.stream_chunks.length > 0 && (
        <details>
          <summary>查看流式传输明细</summary>
          <pre>{[...item.stream_chunks]
            .sort((a, b) => a.position - b.position)
            .map((chunk) => `#${chunk.position}  ${chunk.content}`)
            .join("\n")}</pre>
        </details>
      )}
      {item.tools?.map((tool, i) => (
        <details key={i}>
          <summary>工具 {i + 1}</summary>
          <pre>{JSON.stringify(tool, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}
