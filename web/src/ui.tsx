import { useEffect, type ReactNode } from "react";
import type { RequestItem } from "./types";

export type IconName =
  | "inbox" | "key" | "code" | "bolt" | "settings" | "spark"
  | "external" | "logout" | "user" | "lock" | "arrow" | "search"
  | "refresh" | "chevron" | "message" | "activity" | "raw" | "copy"
  | "plus" | "shield" | "clock" | "back" | "send" | "check" | "bell";

export function LogoMark({ size = 40 }: { size?: number }) {
  return (
    <svg className="logoMark" width={size} height={size} viewBox="0 0 512 512" role="img" aria-label="iamllm">
      <rect width="512" height="512" rx="112" fill="#111A16" />
      <path fill="#F7F8F3" d="M112 76h288c42 0 76 34 76 76v176c0 42-34 76-76 76H258l-106 72v-72h-40c-42 0-76-34-76-76V152c0-42 34-76 76-76Z" />
      <circle cx="256" cy="174" r="30" fill="#111A16" />
      <path d="M256 234v70" fill="none" stroke="#111A16" strokeWidth="38" strokeLinecap="round" />
      <path d="M120 334h82l27-41 42 75 31-56 28 22h62" fill="none" stroke="#B9E83F" strokeWidth="20" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    inbox: <><path d="M4 4h16v13H4z"/><path d="M4 13h4l2 3h4l2-3h4"/></>,
    key: <><circle cx="8" cy="15" r="4"/><path d="m11 12 8-8m-3 3 2 2m-5 1 2 2"/></>,
    code: <><path d="m8 9-4 3 4 3m8-6 4 3-4 3m-3-9-2 12"/></>,
    bolt: <path d="m13 2-9 12h7l-1 8 9-12h-7z"/>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
    spark: <><path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9z"/><path d="m5 14 .7 2.3L8 17l-2.3.7L5 20l-.7-2.3L2 17l2.3-.7z"/></>,
    external: <><path d="M14 4h6v6m0-6-9 9"/><path d="M19 13v7H4V5h7"/></>,
    logout: <><path d="M10 4H4v16h6m4-4 4-4-4-4m4 4H9"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4 3.4-6 8-6s7.2 2 8 6"/></>,
    lock: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    arrow: <path d="m9 18 6-6-6-6"/>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    refresh: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    message: <path d="M4 5h16v12H8l-4 4z"/>,
    activity: <path d="M3 12h4l2-7 4 14 2-7h6"/>,
    raw: <><path d="M8 4H4v16h4m8-16h4v16h-4"/><path d="m13 8-2 8"/></>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    shield: <path d="M12 3 4 6v5c0 5 3.4 8.3 8 10 4.6-1.7 8-5 8-10V6z"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    back: <path d="m15 18-6-6 6-6"/>,
    send: <><path d="m3 3 18 9-18 9 4-9z"/><path d="M7 12h14"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function PageHead({ eyebrow, title, subtitle, children }: { eyebrow: string; title: string; subtitle: string; children?: ReactNode }) {
  return <header className="pageHead"><div><small>{eyebrow}</small><h1>{title}</h1><p>{subtitle}</p></div>{children}</header>;
}

export function Toast({ text, close }: { text: string; close: () => void }) {
  useEffect(() => {
    const timer = setTimeout(close, 4000);
    return () => clearTimeout(timer);
  }, [text, close]);
  return <div className="toast" onClick={close}>{text}</div>;
}

export function Empty({ large = false, search = false }: { large?: boolean; search?: boolean }) {
  return <div className={`empty ${large ? "large" : ""}`}><b>{search ? <Icon name="search" /> : <Icon name="check" />}</b><h3>{search ? "没有匹配的会话" : "队列已经清空"}</h3><p>{search ? "换个关键词，或清空搜索条件。" : "新问题到达后会自动出现在这里。"}</p></div>;
}

export function ConversationEmpty({ filter }: { filter: string }) {
  return <div className="conversationEmpty"><div className="emptyOrb"><span /><Icon name={filter === "pending" ? "inbox" : "message"} size={28} /></div><small>{filter === "pending" ? "INBOX ZERO" : "CONVERSATION ARCHIVE"}</small><h2>{filter === "pending" ? "现在没有人等你" : "从左侧选择一段会话"}</h2><p>{filter === "pending" ? "去喝口水吧。新问题抵达时，这里会自动亮起来。" : "聊天、运行记录和原始上下文会在这里展开。"}</p>{filter === "pending" && <div className="emptyTip"><i className="online" /> 实时连接正常</div>}</div>;
}

export function stateLabel(item: RequestItem) {
  return item.status === "pending" ? "待处理" : item.status === "answered" ? "已回答" : "已过期";
}

export function sourceLabel(source: string) {
  return ({ openai_chat: "OpenAI Chat", openai_responses: "OpenAI Responses", anthropic_messages: "Claude Messages", gemini_generate: "Gemini", human_job: "Human Job", web_chat: "Playground", api: "API 联调" } as Record<string, string>)[source] || source;
}

export function relative(value: number) {
  const milliseconds = value > 1e11 ? value : value * 1000;
  const diff = Math.max(0, Date.now() - milliseconds);
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
  return new Date(milliseconds).toLocaleDateString();
}

export function formatDateTime(value: number) {
  if (!value) return "尚无记录";
  const milliseconds = value > 1e11 ? value : value * 1000;
  return new Date(milliseconds).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function compact(value: number) {
  return value > 999999 ? `${(value / 1e6).toFixed(1)}M` : value > 999 ? `${Math.round(value / 1000)}K` : String(value);
}
