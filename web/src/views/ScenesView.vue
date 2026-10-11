<script setup lang="ts">
import { CopyDocument } from "@element-plus/icons-vue";
import { computed, onBeforeUnmount } from "vue";
import { buildSceneExecuteCurl } from "../apiExamples";
import type { HomeItem, SceneItem } from "../types/admin";
import { copyText } from "../utils/copyText";
import type { AdminRequest } from "../types/control";
import { useSceneControl, type SceneControlMemory } from "../composables/useSceneControl";

const props = defineProps<{
  scenes: SceneItem[];
  homes: HomeItem[];
  apiBaseUrl: string;
  oneTimeApiKey: string;
  pendingIds: string[];
  request: AdminRequest;
  controlMemory?: SceneControlMemory;
}>();

const emit = defineEmits<{
  "auto-save-executable": [scene: SceneItem, value: string | number | boolean];
  "auto-save-hidden": [scene: SceneItem, value: string | number | boolean];
  "check-devices": [];
}>();
const { selected, visible, outcome, busy, canExecute, openScene, closeScene, acknowledgeUnknown, executeScene } = useSceneControl({ request: props.request, getScene: (id) => props.scenes.find((scene) => scene.id === id), memory: props.controlMemory });
onBeforeUnmount(closeScene);

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
            :disabled="pendingIds.includes(row.id)"
            @change="(value: string | number | boolean) => emit('auto-save-executable', row, value)"
          />
        </template>
      </el-table-column>
      <el-table-column label="隐藏" width="90">
        <template #default="{ row }">
          <el-switch
            v-model="row.hidden"
            :disabled="pendingIds.includes(row.id)"
            @change="(value: string | number | boolean) => emit('auto-save-hidden', row, value)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }"><el-button size="small" type="primary" :disabled="!row.executable || row.hidden || pendingIds.includes(row.id)" @click="openScene(row)">执行场景</el-button></template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="visible" class="app-dialog" title="手动执行场景" width="min(520px, 94vw)" @close="closeScene">
      <template v-if="selected">
        <p>场景：<strong>{{ selected.name }}</strong> · {{ homeName(selected.home_id) }}</p>
        <p>点击确认后将执行该场景中的设备操作。</p>
        <el-alert v-if="!selected.executable || selected.hidden" type="info" title="场景未获执行授权或已隐藏，请先调整授权" :closable="false" />
        <el-alert v-if="outcome" :type="outcome.status === 'success' ? 'success' : outcome.status === 'unknown' ? 'warning' : 'error'" :title="outcome.message" :closable="false">
          <template v-if="outcome.status === 'unknown'">
            <p>请求不会自动重发。请先在家庭与设备中核对实际状态，避免重复执行场景。</p>
            <el-button size="small" @click="emit('check-devices')">查看设备状态</el-button>
            <el-button size="small" @click="acknowledgeUnknown">已核对结果，允许再次手动执行</el-button>
          </template>
        </el-alert>
      </template>
      <el-alert v-else type="warning" title="所选场景已从资源列表移除，请关闭并重新同步" :closable="false" />
      <template #footer>
        <el-button @click="closeScene">关闭</el-button>
        <el-button type="primary" :loading="busy" :disabled="!canExecute || Boolean(selected && pendingIds.includes(selected.id))" @click="executeScene">确认执行场景</el-button>
      </template>
    </el-dialog>
  </section>
</template>
