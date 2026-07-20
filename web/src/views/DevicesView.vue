<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { DeviceItem, HomeItem } from "../types/admin";

const props = defineProps<{
  devices: DeviceItem[];
  homes: HomeItem[];
  syncing: boolean;
}>();

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
          <el-input v-model="row.slug" />
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
            @change="(value: string | number | boolean) => emit('auto-save-access', row, value)"
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
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button size="small" @click="emit('update-device', row)">保存</el-button>
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
  </section>
</template>
