<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { apiPermissionRows } from "../data/apiDocs";
import type { ApiKeyItem, CreateApiKeyPayload, DeviceItem, HomeItem, SceneItem } from "../types/admin";
import { createKeyPayload, expiryForMode, type ExpiryMode } from "../utils/apiKeyForm";
import ApiKeyExpiryInput from "../components/ApiKeyExpiryInput.vue";

const props = defineProps<{
  apiKeys: ApiKeyItem[];
  oneTimeApiKey: string;
  homes: HomeItem[];
  devices: DeviceItem[];
  scenes: SceneItem[];
  creating: boolean;
  busyKeyId: string;
}>();

const emit = defineEmits<{
  create: [payload: CreateApiKeyPayload];
  "set-status": [key: ApiKeyItem, active: boolean];
  delete: [key: ApiKeyItem];
  rotate: [key: ApiKeyItem, payload: { expires_at?: string | null }];
}>();

const keyForm = reactive({
  name: "",
  scopes: ["read:status", "read:devices"] as string[],
  policy: { homes: [] as string[], devices: [] as string[], scenes: [] as string[] },
  unrestricted: { homes: true, devices: true, scenes: true },
  expiresAt: "",
});
const rotateKey = ref<ApiKeyItem | null>(null);
const createExpiryMode = ref<ExpiryMode>("never");
const rotateExpiry = ref("");
const rotateExpiryMode = ref<ExpiryMode>("inherit");

watch(
  () => props.oneTimeApiKey,
  (key, previous) => {
    if (key && key !== previous) {
      keyForm.name = "";
      rotateKey.value = null;
    }
  }
);

function toggleApiKeyScope(scope: string, checked: string | number | boolean): void {
  const selected = Boolean(checked);
  const scopes = new Set(keyForm.scopes);
  if (selected) {
    scopes.add(scope);
  } else {
    scopes.delete(scope);
  }
  keyForm.scopes = Array.from(scopes);
}

function onCreate(): void {
  try {
    const expiresAt = expiryForMode(createExpiryMode.value, keyForm.expiresAt);
    emit("create", createKeyPayload({ ...keyForm, expiresAt: expiresAt || "" }));
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建参数无效");
  }
}

function openRotate(key: ApiKeyItem): void {
  rotateKey.value = key;
  rotateExpiry.value = "";
  rotateExpiryMode.value = isExpired(key) ? "custom" : "inherit";
}

function isExpired(key: ApiKeyItem): boolean {
  return Boolean(key.expires_at && new Date(key.expires_at).getTime() <= Date.now());
}

function onRotate(): void {
  if (!rotateKey.value) return;
  try {
    const payload: { expires_at?: string | null } = {};
    const expiresAt = expiryForMode(rotateExpiryMode.value, rotateExpiry.value);
    if (expiresAt !== undefined) payload.expires_at = expiresAt;
    emit("rotate", rotateKey.value, payload);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "轮换参数无效");
  }
}
</script>

<template>
  <section class="stack">
    <el-card shadow="never">
      <template #header>创建 API Key</template>
      <el-form label-width="96px">
        <el-form-item label="名称">
          <el-input v-model="keyForm.name" />
        </el-form-item>
        <el-form-item label="权限">
          <el-table :data="apiPermissionRows" border class="permission-table">
            <el-table-column label="选择" width="80" align="center">
              <template #default="{ row }">
                <el-checkbox
                  :model-value="keyForm.scopes.includes(row.scope)"
                  @change="(checked: string | number | boolean) => toggleApiKeyScope(row.scope, checked)"
                />
              </template>
            </el-table-column>
            <el-table-column label="权限" width="170">
              <template #default="{ row }">
                <div class="permission-name">{{ row.name }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="260" />
            <el-table-column label="风险" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="row.level" effect="light">
                  {{ row.level === "danger" ? "高" : row.level === "warning" ? "中" : "低" }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="家庭范围">
          <el-checkbox v-model="keyForm.unrestricted.homes">全部家庭</el-checkbox>
          <el-select v-model="keyForm.policy.homes" multiple filterable :disabled="keyForm.unrestricted.homes" placeholder="选择允许的家庭">
            <el-option v-for="home in homes" :key="home.id" :label="home.name" :value="home.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备范围">
          <el-checkbox v-model="keyForm.unrestricted.devices">全部设备</el-checkbox>
          <el-select v-model="keyForm.policy.devices" multiple filterable :disabled="keyForm.unrestricted.devices" placeholder="选择允许的设备">
            <el-option v-for="device in devices" :key="device.id" :label="device.display_name || device.name" :value="device.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景范围">
          <el-checkbox v-model="keyForm.unrestricted.scenes">全部场景</el-checkbox>
          <el-select v-model="keyForm.policy.scenes" multiple filterable :disabled="keyForm.unrestricted.scenes" placeholder="选择允许的场景">
            <el-option v-for="scene in scenes" :key="scene.id" :label="scene.name" :value="scene.id" />
          </el-select>
        </el-form-item>
        <el-alert type="info" :closable="false" title="家庭、设备、场景范围分别限制对应资源列表；限制某个家庭时，请同时选择该家庭允许的设备与场景。设备可控和场景可执行开关仍需单独开启。" />
        <el-form-item label="过期时间">
          <ApiKeyExpiryInput v-model:mode="createExpiryMode" v-model:value="keyForm.expiresAt" />
        </el-form-item>
        <el-button type="primary" :loading="creating" :disabled="creating" @click="onCreate">创建</el-button>
      </el-form>
      <el-alert v-if="oneTimeApiKey" class="one-time-key" type="warning" show-icon :closable="false">
        <template #title>一次性密钥，只显示这一次</template>
        <div class="api-key-value">{{ oneTimeApiKey }}</div>
      </el-alert>
    </el-card>
    <el-table :data="apiKeys" border>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="key_prefix" label="前缀" min-width="160" show-overflow-tooltip>
        <template #default="{ row }"><code class="api-key-prefix">{{ row.key_prefix }}</code></template>
      </el-table-column>
      <el-table-column label="权限" min-width="180">
        <template #default="{ row }">{{ row.scopes.join('，') }}</template>
      </el-table-column>
      <el-table-column label="资源范围" min-width="160">
        <template #default="{ row }">
          家庭 {{ row.resource_policy?.homes?.length || '全部' }} / 设备 {{ row.resource_policy?.devices?.length || '全部' }} / 场景 {{ row.resource_policy?.scenes?.length || '全部' }}
        </template>
      </el-table-column>
      <el-table-column label="过期时间" min-width="180">
        <template #default="{ row }">{{ row.expires_at ? new Date(new Date(row.expires_at).getTime() - 1).toLocaleDateString() : '不过期' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="!row.is_active ? 'info' : isExpired(row) ? 'warning' : 'success'">
            {{ !row.is_active ? "停用" : isExpired(row) ? "已过期" : "启用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="use_count" label="调用次数" width="100" />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <div class="api-key-actions">
            <el-button size="small" :disabled="Boolean(busyKeyId)" @click="emit('set-status', row, !row.is_active)">{{ row.is_active ? '停用' : '启用' }}</el-button>
            <el-button size="small" :disabled="Boolean(busyKeyId)" @click="openRotate(row)">轮换</el-button>
            <el-button size="small" type="danger" :disabled="Boolean(busyKeyId)" @click="emit('delete', row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog :model-value="Boolean(rotateKey)" :close-on-click-modal="!busyKeyId" :close-on-press-escape="!busyKeyId" title="轮换 API Key" width="min(480px, 92vw)" class="app-dialog" @update:model-value="(visible: boolean) => { if (!visible && !busyKeyId) rotateKey = null; }">
      <p>为「{{ rotateKey?.name }}」生成新密钥并停用旧密钥。权限和资源范围继承，旧密钥在轮换成功后失效。</p>
      <ApiKeyExpiryInput v-model:mode="rotateExpiryMode" v-model:value="rotateExpiry" allow-inherit />
      <template #footer>
        <el-button :disabled="Boolean(busyKeyId)" @click="rotateKey = null">取消</el-button>
        <el-button type="primary" :loading="Boolean(busyKeyId)" :disabled="Boolean(busyKeyId)" @click="onRotate">确认轮换</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.api-key-prefix,
.api-key-actions {
  white-space: nowrap;
}

.api-key-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .permission-table {
    font-size: 13px;
  }
}

.api-key-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
