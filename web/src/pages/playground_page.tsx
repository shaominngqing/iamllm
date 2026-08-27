import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Icon, LogoMark } from "../ui";

export function PlaygroundPage() {
  const [draft, setDraft] = useState(""),
    [messages, setMessages] = useState<
      { role: "user" | "assistant"; content: string }[]
    >([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  async function send() {
    const value = draft.trim();
    if (!value || busy) return;
    const history = [...messages, { role: "user" as const, content: value }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const request = () =>
        fetch("/admin/api/v1/playground/chat/completions", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${api.access}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ stream: true, messages: history }),
        });
      let response = await request();
      if (response.status === 401 && api.refreshToken) {
        await api.refresh();
        response = await request();
      }
      if (!response.ok)
        throw new Error(
          (await response.text()) || `请求失败 (${response.status})`,
        );
      const reader = response.body?.getReader(),
        decoder = new TextDecoder();
      let buffer = "",
        answer = "";
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
          try {
            const chunk = JSON.parse(line.slice(6));
            answer += chunk.choices?.[0]?.delta?.content || "";
            setMessages([...history, { role: "assistant", content: answer }]);
          } catch {}
        }
      }
    } catch (e) {
      setMessages(history);
      setError(e instanceof Error ? e.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="playground">
      <header>
        <div>
          <LogoMark size={40} />
          <span>
            <b>iamllm Playground</b>
            <small><i className="online" /> 管理员测试通道</small>
          </span>
        </div>
        <a href="/admin">管理控制台 <Icon name="external" size={14} /></a>
      </header>
      <main>
        <section className="playChat">
          {messages.length === 0 && (
            <div className="playWelcome">
              <LogoMark size={58} />
              <small>HUMAN MODEL, STANDARD API</small>
              <h1>今天想聊点什么？</h1>
              <p>
                无需填写接入参数，直接使用当前服务配置。消息会进入管理工作台，并实时接收回复。
              </p>
              <div className="promptSuggestions">
                {["介绍一下你自己", "看图能力怎么测试？", "给我一个奇怪的点子"].map((value) => <button key={value} onClick={() => setDraft(value)}>{value}<Icon name="arrow" size={13} /></button>)}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div className={`playBubble ${m.role}`} key={i}>
              <small>{m.role === "user" ? "你" : "iamllm"}</small>
              <p>{m.content || "正在等回复…"}</p>
            </div>
          ))}
          <div ref={bottom} />
        </section>
        <section className="playComposer">
          {error && <div className="playError">{error}</div>}
          <div className="playComposerNote">
            <span><i className="online" /> 已使用当前服务配置</span>
            <small>对话历史会自动随消息发送</small>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="问点什么；Enter 发送，Shift + Enter 换行"
          />
          <button disabled={busy || !draft.trim()} onClick={send}>
            {busy ? "等待模型…" : <>发送 <Icon name="send" size={16} /></>}
          </button>
        </section>
      </main>
    </div>
  );
}
