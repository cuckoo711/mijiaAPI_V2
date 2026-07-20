<script setup lang="ts">
import { reactive, watch } from "vue";
import { apiPermissionRows } from "../data/apiDocs";
import type { ApiKeyItem } from "../types/admin";

const props = defineProps<{
  apiKeys: ApiKeyItem[];
  oneTimeApiKey: string;
}>();

const emit = defineEmits<{
  create: [payload: { name: string; scopes: string[] }];
}>();

const keyForm = reactive({
  name: "",
  scopes: ["read:status", "read:devices"] as string[],
});

watch(
  () => props.oneTimeApiKey,
  (key, previous) => {
    if (key && key !== previous) {
      keyForm.name = "";
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
  emit("create", { name: keyForm.name, scopes: [...keyForm.scopes] });
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
        <el-button type="primary" @click="onCreate">创建</el-button>
      </el-form>
      <el-alert v-if="oneTimeApiKey" class="one-time-key" type="warning" show-icon :closable="false">
        <template #title>一次性密钥，只显示这一次</template>
        <div class="api-key-value">{{ oneTimeApiKey }}</div>
      </el-alert>
    </el-card>
    <el-table :data="apiKeys" border>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="key_prefix" label="前缀" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? "启用" : "停用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="use_count" label="调用次数" width="100" />
    </el-table>
  </section>
</template>
