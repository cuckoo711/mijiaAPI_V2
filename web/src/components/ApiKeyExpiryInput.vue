<script setup lang="ts">
import zhCn from "element-plus/es/locale/lang/zh-cn";
import type { ExpiryMode } from "../utils/apiKeyForm";

defineProps<{ mode: ExpiryMode; value: string; allowInherit?: boolean }>();
const emit = defineEmits<{
  "update:mode": [value: ExpiryMode];
  "update:value": [value: string];
}>();

function disabledDate(date: Date): boolean {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return date.getTime() < today.getTime();
}
</script>

<template>
  <div class="expiry-input">
    <el-select :model-value="mode" aria-label="有效期" @update:model-value="emit('update:mode', $event)">
      <el-option v-if="allowInherit" label="继承原过期时间" value="inherit" />
      <el-option label="不过期" value="never" />
      <el-option v-for="days in [30, 90, 180]" :key="days" :label="`${days} 天后过期`" :value="String(days)" />
      <el-option label="自定义过期时间" value="custom" />
    </el-select>
    <el-config-provider :locale="zhCn">
      <el-date-picker
        v-if="mode === 'custom'"
        :model-value="value"
        type="datetime"
        value-format="YYYY-MM-DDTHH:mm:ss"
        format="YYYY-MM-DD HH:mm:ss"
        placeholder="选择过期日期和时间"
        aria-label="过期日期和时间"
        :disabled-date="disabledDate"
        @update:model-value="emit('update:value', $event || '')"
      />
    </el-config-provider>
    <span v-if="mode === '30' || mode === '90' || mode === '180'" class="expiry-hint">从提交时起计算有效期</span>
  </div>
</template>

<style scoped>
.expiry-input {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
}
.expiry-input .el-select {
  width: 220px;
  max-width: 100%;
}
.expiry-input :deep(.el-date-editor) {
  width: 260px;
  max-width: 100%;
}
.expiry-hint {
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
