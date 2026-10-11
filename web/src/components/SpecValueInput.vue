<script setup lang="ts">
import type { SpecValue } from "../types/control";

defineProps<{ spec: SpecValue; modelValue?: string; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
</script>

<template>
  <div class="spec-value-input">
    <el-select v-if="spec.value_list != null" :model-value="modelValue" :disabled="disabled" placeholder="选择枚举值" @update:model-value="(value: string) => emit('update:modelValue', value)">
      <el-option v-for="(value, index) in spec.value_list" :key="index" :label="String(value)" :value="String(value)" />
    </el-select>
    <el-select v-else-if="spec.type === 'bool'" :model-value="modelValue" :disabled="disabled" placeholder="选择 true / false" @update:model-value="(value: string) => emit('update:modelValue', value)">
      <el-option label="true" value="true" />
      <el-option label="false" value="false" />
    </el-select>
    <el-input v-else :model-value="modelValue" :disabled="disabled" :inputmode="spec.type === 'string' ? 'text' : 'decimal'" :placeholder="spec.type === 'string' ? '输入文本值' : '输入数值'" @update:model-value="(value: string) => emit('update:modelValue', value)" />
    <small>{{ spec.type }}<template v-if="spec.value_range"> · 范围 {{ spec.value_range[0] }} 至 {{ spec.value_range[1] }}<template v-if="spec.value_range.length === 3">，步长 {{ spec.value_range[2] }}</template></template></small>
  </div>
</template>

<style scoped>
.spec-value-input { width: 100%; }
.spec-value-input small { display: block; margin-top: 5px; color: #6b7280; }
</style>
