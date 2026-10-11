<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import type { DeviceItem, HomeItem } from "../types/admin";
import type { AdminRequest, DeviceState } from "../types/control";
import { useDeviceControl, type DeviceControlMemory } from "../composables/useDeviceControl";
import { actionKey, parameterKey, propertyKey } from "../utils/controlForm";
import SpecValueInput from "../components/SpecValueInput.vue";

const props = defineProps<{
  devices: DeviceItem[];
  homes: HomeItem[];
  syncing: boolean;
  pendingIds: string[];
  request: AdminRequest;
  controlMemory?: DeviceControlMemory;
}>();

const {
  selected, visible, spec, state, stateUpdatedAt, loadError, stateError,
  specLoading, stateLoading, controlBusy, draft, outcome, requiresVerification,
  canAcknowledge, canControl, writableProperties, selectedProperty, selectedAction,
  openDevice, closeDevice, refreshSpec, refreshState, chooseAction, acknowledgeUnknown,
  writeProperty, callAction,
} = useDeviceControl({ request: props.request, getDevice: (id) => props.devices.find((device) => device.id === id), memory: props.controlMemory });
onBeforeUnmount(closeDevice);

function stateName(siid: number, piid: number): string {
  return spec.value?.properties.find((property) => property.siid === siid && property.piid === piid)?.name || `${siid}.${piid}`;
}

function displayValue(value: unknown): string {
  return value === undefined ? "未返回值" : JSON.stringify(value);
}

function stateReadLabel(item: DeviceState): string {
  if (typeof item.code === "number" && item.code !== 0) return `错误 ${item.code}`;
  return item.code === 0 && Object.prototype.hasOwnProperty.call(item, "value") && item.value !== undefined
    ? "已读取"
    : "结果未确认";
}

const emit = defineEmits<{
  sync: [];
  "update-device": [device: DeviceItem];
  "auto-save-access": [device: DeviceItem, value: string | number | boolean];
  "auto-save-hidden": [device: DeviceItem, value: string | number | boolean];
}>();

const devicePage = ref(1);
const devicePageSize = ref(20);
const deviceFilters = reactive({
  home: "",
  status: "",
  access: "",
  hidden: "",
});

const homeNameMap = computed(() => new Map(props.homes.map((home) => [home.id, home.name])));

const filteredDevices = computed(() => {
  return props.devices.filter((device) => {
    if (deviceFilters.home && device.home_id !== deviceFilters.home) {
      return false;
    }
    if (deviceFilters.status && device.status !== deviceFilters.status) {
      return false;
    }
    if (deviceFilters.access && device.access_mode !== deviceFilters.access) {
      return false;
    }
    if (deviceFilters.hidden && String(device.hidden) !== deviceFilters.hidden) {
      return false;
    }
    return true;
  });
});

const paginatedDevices = computed(() => {
  const start = (devicePage.value - 1) * devicePageSize.value;
  return filteredDevices.value.slice(start, start + devicePageSize.value);
});

watch(deviceFilters, () => {
  devicePage.value = 1;
});

watch([filteredDevices, devicePageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredDevices.value.length / devicePageSize.value));
  if (devicePage.value > maxPage) {
    devicePage.value = maxPage;
  }
});

function homeName(homeId: string): string {
  return homeNameMap.value.get(homeId) || homeId || "-";
}

function resetDeviceFilters(): void {
  deviceFilters.home = "";
  deviceFilters.status = "";
  deviceFilters.access = "";
  deviceFilters.hidden = "";
}

function deviceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    online: "在线",
    offline: "离线",
    unknown: "未知",
  };
  return labels[status] || status || "-";
}

function deviceStatusTag(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "online") {
    return "success";
  }
  if (status === "offline") {
    return "danger";
  }
  if (status === "unknown") {
    return "warning";
  }
  return "info";
}
</script>

<template>
  <section class="devices-page">
    <div class="device-filter-bar">
      <el-button :loading="syncing" :disabled="syncing" @click="emit('sync')">
        {{ syncing ? "同步中..." : "重新同步" }}
      </el-button>
      <el-select v-model="deviceFilters.home" clearable placeholder="家庭" class="filter-control">
        <el-option v-for="home in homes" :key="home.id" :label="home.name" :value="home.id" />
      </el-select>
      <el-select v-model="deviceFilters.status" clearable placeholder="状态" class="filter-control">
        <el-option label="在线" value="online" />
        <el-option label="离线" value="offline" />
        <el-option label="未知" value="unknown" />
      </el-select>
      <el-select v-model="deviceFilters.access" clearable placeholder="访问" class="filter-control">
        <el-option label="只读" value="read" />
        <el-option label="可控" value="write" />
      </el-select>
      <el-select v-model="deviceFilters.hidden" clearable placeholder="隐藏" class="filter-control">
        <el-option label="显示" value="false" />
        <el-option label="隐藏" value="true" />
      </el-select>
      <el-button @click="resetDeviceFilters">重置</el-button>
    </div>
    <el-table :data="paginatedDevices" border height="100%" class="devices-table">
      <el-table-column label="显示名" min-width="180">
        <template #default="{ row }">
          <span class="readonly-name">{{ row.display_name || row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Slug" min-width="180">
        <template #default="{ row }">
          <el-input v-model="row.slug" :disabled="pendingIds.includes(row.id)" />
        </template>
      </el-table-column>
      <el-table-column label="家庭" min-width="160">
        <template #default="{ row }">
          {{ homeName(row.home_id) }}
        </template>
      </el-table-column>
      <el-table-column prop="model" label="型号" min-width="180" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="deviceStatusTag(row.status)" effect="light">
            {{ deviceStatusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="访问" width="140">
        <template #default="{ row }">
          <el-switch
            v-model="row.access_mode"
            active-value="write"
            inactive-value="read"
            active-text="可控"
            inactive-text="只读"
            inline-prompt
            class="access-switch"
            :disabled="pendingIds.includes(row.id)"
            @change="(value: string | number | boolean) => emit('auto-save-access', row, value)"
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
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :loading="pendingIds.includes(row.id)" :disabled="pendingIds.includes(row.id)" @click="emit('update-device', row)">保存</el-button>
          <el-button size="small" @click="openDevice(row)">状态与控制</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="table-pagination">
      <el-pagination
        v-model:current-page="devicePage"
        v-model:page-size="devicePageSize"
        :page-sizes="[20, 50, 100]"
        :total="filteredDevices.length"
        background
        layout="total, sizes, prev, pager, next"
      />
    </div>
    <el-dialog v-model="visible" :title="`${selected?.display_name || selected?.name || '设备'} · 状态与控制`" width="min(920px, 94vw)" @close="closeDevice">
      <div v-if="selected" class="device-control-panel">
        <el-alert v-if="selected.access_mode !== 'write' || selected.hidden" type="info" :closable="false" :title="selected.hidden ? '设备已隐藏，仅可查看状态；请先取消隐藏并授予可控权限再控制' : '设备为只读，仅可查看状态；请先授予可控权限再控制'" />
        <el-alert v-if="outcome" :type="outcome.status === 'success' ? 'success' : outcome.status === 'unknown' ? 'warning' : 'error'" :title="outcome.message" :closable="false">
          <template v-if="requiresVerification">
            <p>请求不会自动重发。请核对下方最新状态和实际设备，再决定是否需要新的操作。</p>
            <el-button size="small" :loading="stateLoading" @click="refreshState">核对最新状态</el-button>
            <el-button size="small" :disabled="!canAcknowledge || stateLoading" @click="acknowledgeUnknown">已核对结果，允许新的手动操作</el-button>
          </template>
        </el-alert>
        <div class="control-section-header">
          <strong>当前属性状态</strong>
          <el-button size="small" :loading="stateLoading" :disabled="stateLoading" @click="refreshState">刷新状态</el-button>
        </div>
        <p v-if="stateUpdatedAt" class="control-help">读取时间：{{ stateUpdatedAt }}。设备列表的在线状态来自上次同步。</p>
        <el-alert v-if="stateError" type="error" :title="stateError" :closable="false" />
        <el-table :data="state" border max-height="260">
          <el-table-column label="属性" min-width="140"><template #default="{ row }">{{ stateName(row.siid, row.piid) }}</template></el-table-column>
          <el-table-column label="SIID / PIID" width="130"><template #default="{ row }">{{ row.siid }} / {{ row.piid }}</template></el-table-column>
          <el-table-column label="值" min-width="120"><template #default="{ row }">{{ displayValue(row.value) }}</template></el-table-column>
          <el-table-column label="读取结果" width="130"><template #default="{ row }">{{ stateReadLabel(row) }}</template></el-table-column>
        </el-table>
        <p v-if="!state.length && !stateLoading && !stateError" class="control-help">设备未返回可读属性，可核对实际设备状态。</p>
        <div class="control-section-header">
          <strong>设备规格与控制</strong>
          <el-button size="small" :loading="specLoading" :disabled="specLoading || controlBusy" @click="refreshSpec">重新读取规格</el-button>
        </div>
        <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" />
        <p v-if="specLoading" class="control-help">正在读取设备规格…</p>
        <template v-if="spec && draft">
          <el-form label-width="110px" @submit.prevent>
            <el-form-item label="写入属性">
              <el-select v-model="draft.property" :disabled="controlBusy" placeholder="选择可写属性">
                <el-option v-for="property in writableProperties" :key="propertyKey(property)" :label="`${property.name} (${property.siid}.${property.piid})`" :value="propertyKey(property)" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="selectedProperty" :label="selectedProperty.name">
              <SpecValueInput v-model="draft.propertyValues[propertyKey(selectedProperty)]" :spec="selectedProperty" :disabled="controlBusy" />
            </el-form-item>
            <el-form-item><el-button type="primary" :loading="controlBusy" :disabled="!canControl || !selectedProperty || pendingIds.includes(selected.id)" @click="writeProperty">确认写入属性</el-button></el-form-item>
          </el-form>
          <el-form label-width="110px" @submit.prevent>
            <el-form-item label="设备动作">
              <el-select :model-value="draft.action" :disabled="controlBusy" placeholder="选择设备动作" @update:model-value="chooseAction">
                <el-option v-for="action in spec.actions" :key="actionKey(action)" :label="`${action.name} (${action.siid}.${action.aiid})`" :value="actionKey(action)" />
              </el-select>
            </el-form-item>
            <template v-if="selectedAction">
              <el-form-item v-for="parameter in selectedAction.parameters" :key="parameterKey(parameter)" :label="`${parameter.name}${parameter.required === false ? '（可选）' : ''}`">
                <SpecValueInput v-model="draft.actionValues[actionKey(selectedAction)][parameterKey(parameter)]" :spec="parameter" :disabled="controlBusy" />
              </el-form-item>
              <p v-if="!selectedAction.parameters.length" class="control-help">该动作无需输入参数。</p>
            </template>
            <el-form-item><el-button type="primary" :loading="controlBusy" :disabled="!canControl || !selectedAction || pendingIds.includes(selected.id)" @click="callAction">确认执行动作</el-button></el-form-item>
          </el-form>
          <p class="control-help">选择规格和填写参数不会控制设备；仅点击确认按钮发送请求。失败或取消后保留输入。</p>
        </template>
      </div>
      <el-alert v-else type="warning" title="所选设备已从资源列表移除，请关闭并重新同步" :closable="false" />
      <template #footer><el-button @click="closeDevice">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.device-control-panel { display: flex; flex-direction: column; gap: 12px; }
.control-section-header { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }
.control-help { margin: 0; color: #6b7280; font-size: 13px; }
</style>
