export type Page = "inbox" | "keys" | "automation" | "connect" | "settings";

export type RequestItem = {
  id: string;
  preview: string;
  status: string;
  source: string;
  model: string;
  created_at: number;
  updated_at: number;
  context_chars: number;
  tool_count: number;
  attachment_count: number;
  stream_chunk_count: number;
  answer?: string;
  claim_owner?: string;
  messages?: Message[];
  raw_messages?: Message[];
  tools?: unknown[];
  stream_chunks?: { content: string; position: number }[];
  client_online?: boolean;
  read_at?: number;
  draft?: string;
  draft_updated_at?: number;
  draft_device_id?: string;
};

export type Message = {
  role: string;
  content: string | Part[] | null;
  tool_calls?: unknown[];
};

export type Part = {
  type: string;
  text?: string;
  image_url?: string | { url: string };
  file?: { filename?: string; url?: string; mime_type?: string };
};

export type KeyItem = {
  id: string;
  name: string;
  key_hint: string;
  active: boolean;
  revoked: boolean;
  rate_limit_per_minute: number;
  daily_limit: number;
  max_concurrent: number;
  usage_minute: number;
  usage_today: number;
  pending_requests: number;
  is_master?: boolean;
};

export type Rule = {
  id?: string;
  name: string;
  rule_type: "keyword" | "schedule";
  match_type?: string;
  pattern?: string;
  response_text: string;
  start_time?: string;
  end_time?: string;
  days: number[];
  delay_seconds: number;
  priority: number;
  active: boolean;
};

export type QuickReply = {
  id?: string;
  title: string;
  content: string;
  category: string;
  active: boolean;
};

export type Profile = {
  display_name: string;
  bio: string;
  skills: string[];
};

export type Overview = {
  model: string;
  runtime: string;
  database: string;
  environment: string;
  public_base_url: string;
  response_timeout_seconds: number;
  stream_chunk_delay_ms: number;
  stream_chunk_chars: number;
};

export type AdminDeviceItem = {
  id: string;
  name: string;
  platform: string;
  device_model?: string;
  os_version?: string;
  app_version?: string;
  locale?: string;
  timezone?: string;
  ip_address?: string;
  user_agent?: string;
  created_at: number;
  updated_at: number;
  last_seen_at?: number;
  revoked_at?: number;
};
