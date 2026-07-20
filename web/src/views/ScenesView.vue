<script setup lang="ts">
import { CopyDocument } from "@element-plus/icons-vue";
import { computed } from "vue";
import { buildSceneExecuteCurl } from "../apiExamples";
import type { HomeItem, SceneItem } from "../types/admin";
import { copyText } from "../utils/copyText";

const props = defineProps<{
  scenes: SceneItem[];
  homes: HomeItem[];
  apiBaseUrl: string;
  oneTimeApiKey: string;
}>();

const emit = defineEmits<{
  "auto-save-executable": [scene: SceneItem, value: string | number | boolean];
  "auto-save-hidden": [scene: SceneItem, value: string | number | boolean];
}>();

const homeNameMap = computed(() => new Map(props.homes.map((home) => [home.id, home.name])));

function homeName(homeId: string): string {
  return homeNameMap.value.get(homeId) || homeId || "-";
}

async function copySceneExecuteCurl(sceneId: string): Promise<void> {
  const curl = buildSceneExecuteCurl({
    sceneId,
    baseUrl: props.apiBaseUrl,
    apiKey: props.oneTimeApiKey,
  });
  const message = props.oneTimeApiKey.trim()
    ? "场景执行命令已复制"
    : "场景执行命令已复制，请替换 YOUR_API_KEY";
  await copyText(curl, message);
}
</script>

<template>
  <section>
    <el-table :data="scenes" border>
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="家庭" min-width="160">
        <template #default="{ row }">
          {{ homeName(row.home_id) }}
        </template>
      </el-table-column>
      <el-table-column label="场景 ID" min-width="260">
        <template #default="{ row }">
          <div class="copyable-id">
            <code>{{ row.scene_id }}</code>
            <el-button
              :icon="CopyDocument"
              circle
              size="small"
              title="复制执行 curl"
              @click="copySceneExecuteCurl(row.scene_id)"
            />
          </div>
        </template>
      </el-table-column>
      <el-table-column label="允许执行" width="120">
        <template #default="{ row }">
          <el-switch
            v-model="row.executable"
            @change="(value: string | number | boolean) => emit('auto-save-executable', row, value)"
          />
        </template>
      </el-table-column>
      <el-table-column label="隐藏" width="90">
        <template #default="{ row }">
          <el-switch
            v-model="row.hidden"
            @change="(value: string | number | boolean) => emit('auto-save-hidden', row, value)"
          />
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>
