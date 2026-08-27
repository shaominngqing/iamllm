import { useEffect, useState } from "react";
import { api } from "../api";
import type { KeyItem } from "../types";
import { Icon, PageHead, Toast } from "../ui";

export function KeysPage() {
  const [items, setItems] = useState<KeyItem[]>([]),
    [created, setCreated] = useState<{
      key: string;
      base_url: string;
      model: string;
    } | null>(null),
    [name, setName] = useState("体验用户"),
    [limits, setLimits] = useState({ minute: 10, daily: 100, concurrent: 3 }),
    [showCreate, setShowCreate] = useState(false),
    [error, setError] = useState("");
  async function load() {
    try {
      setItems(
        (await api.request<{ items: KeyItem[] }>("/admin/api/v1/api-keys"))
          .items,
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    load();
  }, []);
  async function create() {
    try {
      const result = await api.request<{
        key: string;
        base_url: string;
        model: string;
      }>("/admin/api/v1/api-keys", {
        method: "POST",
        body: JSON.stringify({
          name,
          rate_limit_per_minute: limits.minute,
          daily_limit: limits.daily,
          max_concurrent: limits.concurrent,
        }),
      });
      setCreated(result);
      setShowCreate(false);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <section className="page narrow">
      <PageHead
        eyebrow="ACCESS CONTROL"
        title="API 密钥"
        subtitle="每个人一把独立钥匙，额度、并发和撤销互不影响。"
      >
        <button onClick={() => setShowCreate(true)}><Icon name="plus" /> 生成新钥匙</button>
      </PageHead>
      {error && <Toast text={error} close={() => setError("")} />}{" "}
      {created && <SecretCard data={created} close={() => setCreated(null)} />}
      {showCreate && (
        <div className="modalBackdrop" onMouseDown={(e) => e.target === e.currentTarget && setShowCreate(false)}>
          <div className="modalCard">
            <button className="modalClose" onClick={() => setShowCreate(false)}>×</button>
            <div className="modalIcon"><Icon name="key" size={22} /></div>
            <small className="eyebrow">NEW ACCESS KEY</small>
            <h2>给谁一把新钥匙？</h2>
            <p>建议按使用者单独创建，之后才能准确限额或撤销。</p>
            <label>备注名称<input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：小王的 OpenCode" /></label>
            <div className="limitGrid">
              <label>每分钟<input type="number" min="1" value={limits.minute} onChange={(e) => setLimits({...limits, minute: Number(e.target.value)})} /></label>
              <label>每天<input type="number" min="1" value={limits.daily} onChange={(e) => setLimits({...limits, daily: Number(e.target.value)})} /></label>
              <label>同时等待<input type="number" min="1" value={limits.concurrent} onChange={(e) => setLimits({...limits, concurrent: Number(e.target.value)})} /></label>
            </div>
            <div className="modalActions"><button className="ghost" onClick={() => setShowCreate(false)}>取消</button><button disabled={!name.trim()} onClick={create}>生成并查看</button></div>
          </div>
        </div>
      )}
      <div className="sectionIntro">
        <div><Icon name="shield" /><span><b>{items.filter((x) => x.active).length} 把钥匙可用</b><small>完整 Key 仅在创建时出现</small></span></div>
        <p>总钥匙由部署环境管理，日常分享请使用可撤销钥匙。</p>
      </div>
      <div className="cards">
        {items.map((item) => (
          <article className="keyCard" key={item.id}>
            <div className="keyIdentity">
              <div className="keyIcon"><Icon name={item.is_master ? "shield" : "key"} /></div>
              <div>
              <span className={`status ${item.active ? "ok" : ""}`}>
                {item.active ? "使用中" : "已停用"}
              </span>
              <h3>{item.name}</h3>
              <code>{item.key_hint}</code>
              </div>
            </div>
            <dl>
              <div>
                <dt>分钟</dt>
                <dd>
                  {item.is_master
                    ? "不限"
                    : `${item.usage_minute}/${item.rate_limit_per_minute}`}
                </dd>
              </div>
              <div>
                <dt>今天</dt>
                <dd>
                  {item.is_master
                    ? "不统计"
                    : `${item.usage_today}/${item.daily_limit}`}
                </dd>
              </div>
              <div>
                <dt>等待中</dt>
                <dd>
                  {item.is_master
                    ? "不限"
                    : `${item.pending_requests}/${item.max_concurrent}`}
                </dd>
              </div>
            </dl>
            {item.is_master ? (
              <span className="status">由部署环境管理</span>
            ) : (
              <button
                className="danger"
                onClick={async () => {
                  await api.request(
                    `/admin/api/v1/api-keys/${item.id}/revoke`,
                    {
                      method: "POST",
                      body: "{}",
                    },
                  );
                  load();
                }}
              >
                撤销
              </button>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
function SecretCard({
  data,
  close,
}: {
  data: { key: string; base_url: string; model: string };
  close: () => void;
}) {
  function download() {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 760;
    const c = canvas.getContext("2d")!;
    c.fillStyle = "#101814";
    c.fillRect(0, 0, 1200, 760);
    c.fillStyle = "#dfff72";
    c.font = "700 64px system-ui";
    c.fillText("iamllm", 70, 105);
    c.fillStyle = "#f5f7f2";
    c.font = "700 40px system-ui";
    c.fillText("接入这位真人模型", 70, 175);
    c.font = "26px monospace";
    [
      ["API", data.base_url + "/v1"],
      ["MODEL", data.model],
      ["KEY", data.key],
    ].forEach(([k, v], i) => {
      c.fillStyle = "#91a197";
      c.fillText(k, 70, 300 + i * 120);
      c.fillStyle = "#f5f7f2";
      c.fillText(v, 250, 300 + i * 120);
    });
    c.fillStyle = "#91a197";
    c.font = "22px system-ui";
    c.fillText("OpenAI · Claude Code · OpenCode · Gemini", 70, 690);
    const a = document.createElement("a");
    a.download = "iamllm-access.png";
    a.href = canvas.toDataURL("image/png");
    a.click();
  }
  return (
    <div className="secret">
      <button className="close" onClick={close}>
        ×
      </button>
      <small>只展示一次</small>
      <h2>新钥匙已经造好</h2>
      <label>
        Base URL<code>{data.base_url}/v1</code>
      </label>
      <label>
        Model<code>{data.model}</code>
      </label>
      <label>
        API Key<code>{data.key}</code>
      </label>
      <div>
        <button onClick={() => navigator.clipboard.writeText(data.key)}>
          复制 Key
        </button>
        <button className="ghost" onClick={download}>
          下载分享卡
        </button>
      </div>
    </div>
  );
}
