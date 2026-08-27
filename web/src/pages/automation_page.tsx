import { useEffect, useState } from "react";
import { api } from "../api";
import type { QuickReply, Rule } from "../types";
import { PageHead } from "../ui";

export function AutomationPage() {
  const [items, setItems] = useState<Rule[]>([]),
    [quickReplies, setQuickReplies] = useState<QuickReply[]>([]),
    [quickForm, setQuickForm] = useState<QuickReply>({
      title: "收到",
      content: "收到，我先看一下。",
      category: "常用",
      active: true,
    }),
    [form, setForm] = useState<Rule>({
      name: "忙碌时打个招呼",
      rule_type: "keyword",
      match_type: "contains",
      pattern: "在吗",
      response_text: "在的，脑子正在开机。",
      days: [0, 1, 2, 3, 4, 5, 6],
      delay_seconds: 2,
      priority: 0,
      active: false,
    });
  async function load() {
    const [rules, replies] = await Promise.all([
      api.request<{ items: Rule[] }>("/admin/api/v1/auto-rules"),
      api.request<{ items: QuickReply[] }>("/admin/api/v1/quick-replies?all=1"),
    ]);
    setItems(rules.items);
    setQuickReplies(replies.items);
  }
  useEffect(() => {
    load();
  }, []);
  async function save() {
    await api.request("/admin/api/v1/auto-rules", {
      method: "POST",
      body: JSON.stringify(form),
    });
    load();
  }
  async function saveQuickReply() {
    await api.request("/admin/api/v1/quick-replies", {
      method: "POST",
      body: JSON.stringify(quickForm),
    });
    setQuickForm({ ...quickForm, title: "", content: "" });
    load();
  }
  return (
    <section className="page narrow">
      <PageHead
        eyebrow="AUTOPILOT"
        title="自动回复"
        subtitle="你不在时先接住场面；命中后直接流式返回，不会闪进人工队列。"
      />
      <div className="twoCol">
        <div className="panel form">
          <h3>新建规则</h3>
          <label>
            规则名
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label>
            触发方式
            <select
              value={form.rule_type}
              onChange={(e) =>
                setForm({
                  ...form,
                  rule_type: e.target.value as Rule["rule_type"],
                })
              }
            >
              <option value="keyword">关键词</option>
              <option value="schedule">时间段</option>
            </select>
          </label>
          {form.rule_type === "keyword" ? (
            <div className="row">
              <label>
                匹配方式
                <select
                  value={form.match_type || "contains"}
                  onChange={(e) =>
                    setForm({ ...form, match_type: e.target.value })
                  }
                >
                  <option value="contains">包含关键词</option>
                  <option value="exact">完全相同</option>
                </select>
              </label>
              <label>
                关键词
                <input
                  value={form.pattern}
                  onChange={(e) =>
                    setForm({ ...form, pattern: e.target.value })
                  }
                />
              </label>
            </div>
          ) : (
            <div className="row">
              <label>
                开始
                <input
                  type="time"
                  value={form.start_time || "10:00"}
                  onChange={(e) =>
                    setForm({ ...form, start_time: e.target.value })
                  }
                />
              </label>
              <label>
                结束
                <input
                  type="time"
                  value={form.end_time || "19:00"}
                  onChange={(e) =>
                    setForm({ ...form, end_time: e.target.value })
                  }
                />
              </label>
            </div>
          )}
          <label>
            回复
            <textarea
              value={form.response_text}
              onChange={(e) =>
                setForm({ ...form, response_text: e.target.value })
              }
            />
          </label>
          <label>
            模拟思考几秒
            <input
              type="number"
              min="0"
              max="300"
              value={form.delay_seconds}
              onChange={(e) =>
                setForm({
                  ...form,
                  delay_seconds: Number(e.target.value) || 0,
                })
              }
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => setForm({ ...form, active: e.target.checked })}
            />
            立即启用
          </label>
          <button onClick={save}>保存规则</button>
        </div>
        <div className="stack">
          {items.map((rule) => (
            <article className="rule" key={rule.id}>
              <span className={`status ${rule.active ? "ok" : ""}`}>
                {rule.active ? "运行中" : "未启用"}
              </span>
              <h3>{rule.name}</h3>
              <p>
                {rule.rule_type === "keyword"
                  ? `“${rule.pattern}” → ${rule.response_text}`
                  : `${rule.start_time}–${rule.end_time} → ${rule.response_text}`}
              </p>
              <div className="ruleActions">
                <button
                  className="ghost"
                  onClick={async () => {
                    await api.request(`/admin/api/v1/auto-rules/${rule.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ active: !rule.active }),
                    });
                    load();
                  }}
                >
                  {rule.active ? "暂停" : "启用"}
                </button>
                <button
                  className="danger"
                  onClick={async () => {
                    await api.request(`/admin/api/v1/auto-rules/${rule.id}`, {
                      method: "DELETE",
                    });
                    load();
                  }}
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
      <div className="automationSection">
        <div>
          <small className="eyebrow">REPLY TOOLBOX</small>
          <h2>快捷回复</h2>
          <p>人工回答时一键填入，确认后才会发送；网页和 Flutter 共用这一组。</p>
        </div>
        <div className="twoCol">
          <div className="panel form">
            <label>
              按钮文字
              <input
                value={quickForm.title}
                onChange={(e) =>
                  setQuickForm({ ...quickForm, title: e.target.value })
                }
              />
            </label>
            <label>
              回复内容
              <textarea
                value={quickForm.content}
                onChange={(e) =>
                  setQuickForm({ ...quickForm, content: e.target.value })
                }
              />
            </label>
            <label>
              分类
              <input
                value={quickForm.category}
                onChange={(e) =>
                  setQuickForm({ ...quickForm, category: e.target.value })
                }
              />
            </label>
            <button
              disabled={!quickForm.title.trim() || !quickForm.content.trim()}
              onClick={saveQuickReply}
            >
              添加快捷回复
            </button>
          </div>
          <div className="stack">
            {quickReplies.map((reply) => (
              <article className="rule" key={reply.id}>
                <span className={`status ${reply.active ? "ok" : ""}`}>
                  {reply.category}
                </span>
                <h3>{reply.title}</h3>
                <p>{reply.content}</p>
                <button
                  className="danger"
                  onClick={async () => {
                    await api.request(
                      `/admin/api/v1/quick-replies/${reply.id}`,
                      { method: "DELETE" },
                    );
                    load();
                  }}
                >
                  删除
                </button>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
