<script setup lang="ts">
import type { CheckItem } from "../types/admin";

defineProps<{
  checks: CheckItem[];
}>();

function checkStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: "通过",
    warn: "提醒",
    fail: "失败",
    info: "信息",
  };
  return labels[status] || status || "-";
}

function checkStatusTag(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "pass") {
    return "success";
  }
  if (status === "fail") {
    return "danger";
  }
  if (status === "warn") {
    return "warning";
  }
  return "info";
}
</script>

<template>
  <section>
    <el-table :data="checks" border>
      <el-table-column label="检查项" min-width="180">
        <template #default="{ row }">
          <div class="check-name">{{ row.label || row.key }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="280" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="checkStatusTag(row.status)">
            {{ checkStatusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="结果" min-width="240" />
    </el-table>
  </section>
</template>
