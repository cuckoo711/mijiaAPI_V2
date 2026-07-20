<script setup lang="ts">
import { reactive } from "vue";

defineProps<{
  configs: Array<Record<string, unknown>>;
}>();

const emit = defineEmits<{
  "set-config": [payload: { key: string; value: string }];
}>();

const configForm = reactive({ key: "PUBLIC_BASE_URL", value: "" });

function onSave(): void {
  emit("set-config", { key: configForm.key, value: configForm.value });
  configForm.value = "";
}
</script>

<template>
  <section class="stack">
    <el-card shadow="never">
      <template #header>运行时配置</template>
      <el-form inline>
        <el-form-item label="Key">
          <el-input v-model="configForm.key" />
        </el-form-item>
        <el-form-item label="Value">
          <el-input v-model="configForm.value" />
        </el-form-item>
        <el-button type="primary" @click="onSave">保存</el-button>
      </el-form>
    </el-card>
    <el-table :data="configs" border>
      <el-table-column prop="key" label="Key" />
      <el-table-column prop="value" label="Value" />
      <el-table-column prop="source" label="来源" width="120" />
    </el-table>
  </section>
</template>
