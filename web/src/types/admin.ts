export type ApiList<T> = { items: T[] };

export type CheckItem = {
  key: string;
  label: string;
  description: string;
  status: string;
  message: string;
};

export type DeviceItem = {
  id: string;
  did_masked: string;
  slug: string;
  name: string;
  alias?: string;
  display_name: string;
  model: string;
  home_id: string;
  tags: string[];
  group_name?: string;
  hidden: boolean;
  access_mode: string;
  status: string;
};

export type HomeItem = {
  id: string;
  name: string;
  uid: string;
  rooms?: Array<Record<string, unknown>>;
  last_synced_at?: string;
};

export type SceneItem = {
  id: string;
  scene_id: string;
  name: string;
  home_id: string;
  hidden: boolean;
  executable: boolean;
};

export type ApiKeyItem = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  created_at: string;
  last_used_at?: string;
  use_count: number;
};

export type ApiEndpointRow = {
  method: "GET" | "POST";
  path: string;
  purpose: string;
  permission: string;
  request: string;
  response: string;
  note: string;
  body?: string;
};

export type AppInfo = {
  name: string;
  version: string;
  description: string;
  license: string;
  authors: string;
  repository_url: string;
  issues_url: string;
  releases_url: string;
};

export type UpdateInfo = {
  current_version: string;
  latest: {
    latest_version: string;
    latest_tag: string;
    published_at: string | null;
    release_url: string;
    release_notes: string;
  } | null;
  update_available: boolean;
  error: string | null;
  checked_at: number;
  repository_url: string;
};

export type ApiPermissionRow = {
  scope: string;
  name: string;
  description: string;
  level: "success" | "warning" | "danger" | "info";
};
