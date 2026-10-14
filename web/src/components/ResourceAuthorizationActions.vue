<script setup lang="ts">
import { ArrowDown, CircleCheck, CircleClose, Setting } from "@element-plus/icons-vue";
defineProps<{ label: string; count: number; busy?: boolean; disabled?: boolean }>();
const emit = defineEmits<{ change: [enabled: boolean] }>();
</script>

<template>
  <div class="resource-authorization-actions">
    <div class="authorization-summary">
      <span class="authorization-label">{{ label }}</span>
      <span class="authorization-default">默认关闭</span>
      <span class="authorization-count">共 {{ count }} 项</span>
    </div>
    <el-dropdown trigger="click" :disabled="disabled || busy || !count" @command="emit('change', $event === 'enable')">
      <el-button class="authorization-trigger" :loading="busy" :disabled="disabled || busy || !count" :icon="Setting">
        批量设置<el-icon class="authorization-arrow"><ArrowDown /></el-icon>
      </el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="enable" :icon="CircleCheck">全部开启{{ label }}</el-dropdown-item>
          <el-dropdown-item command="disable" :icon="CircleClose" divided class="authorization-disable">全部关闭{{ label }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.resource-authorization-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}
.authorization-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.authorization-label {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}
.authorization-default {
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-muted);
  font-size: 12px;
}
.authorization-count {
  color: var(--text-secondary);
  font-size: 12px;
}
.authorization-trigger {
  border-color: var(--border-default);
  font-weight: 500;
}
.authorization-arrow {
  margin-left: 8px;
  color: var(--text-muted);
}
.authorization-disable {
  color: var(--el-color-danger);
}
</style>
