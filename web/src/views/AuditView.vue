<script setup lang="ts">
import type { AuditQueueHealth } from "../types/admin";

defineProps<{
  audits: Array<Record<string, unknown>>;
  health: AuditQueueHealth | null;
  loading: boolean;
  replaying: boolean;
  error: string;
}>();
const emit = defineEmits<{ refresh: []; replay: [] }>();

function resultLabel(value: unknown): string {
  return ({ success: "成功", failed: "失败", warning: "部分成功 / 警告", unknown: "结果未知" } as Record<string, string>)[String(value)] || String(value || "未标注");
}

function resultType(value: unknown): "success" | "danger" | "warning" | "info" {
  if (value === "success") return "success";
  if (value === "failed") return "danger";
  if (value === "warning" || value === "unknown") return "warning";
  return "info";
}

function metadataText(value: unknown): string {
  if (value == null) return "无附加数据";
  try { return JSON.stringify(value, null, 2) || "无附加数据"; }
  catch { return "元数据无法显示"; }
}
</script>

<template>
  <section class="stack">
    <el-card shadow="never">
      <template #header>审计补写队列</template>
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <el-alert v-if="health" :type="health.unavailable ? 'error' : health.pending || health.invalid ? 'warning' : 'success'" :closable="false" :title="health.unavailable ? '本进程存在未能保存的历史审计事件' : health.pending || health.invalid ? '审计队列存在待处理记录' : '审计补写队列正常'">
        待补写 {{ health.pending }} 条 · 无效 {{ health.invalid }} 条 · 历史未能保存 {{ health.unavailable }} 条。
        <span v-if="health.unavailable">这些未保存事件无法补写，请排查日志与存储；就绪状态会持续降级，排查完成后需重启服务。</span>
        <span v-if="health.invalid">无效记录需排查队列文件；补写不会执行任何设备操作。</span>
      </el-alert>
      <p v-else>队列状态尚未读取，请刷新查看。</p>
      <div class="audit-actions">
        <el-button :loading="loading" :disabled="loading || replaying" @click="emit('refresh')">刷新审计</el-button>
        <el-button type="primary" :loading="replaying" :disabled="loading || replaying" @click="emit('replay')">补写审计</el-button>
      </div>
      <p class="audit-help">补写仅重存队列中的审计记录；只在点击按钮后提交。</p>
    </el-card>
    <el-table :data="audits" row-key="id" border>
      <el-table-column type="expand" width="44">
        <template #default="{ row }"><pre class="audit-metadata">{{ metadataText(row.metadata) }}</pre></template>
      </el-table-column>
      <el-table-column prop="occurred_at" label="时间" min-width="190" />
      <el-table-column prop="action" label="动作" min-width="180" show-overflow-tooltip />
      <el-table-column prop="actor_type" label="操作者类型" width="120" />
      <el-table-column label="操作者 ID" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ row.actor_id || '未提供' }}</template></el-table-column>
      <el-table-column label="请求 ID" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.request_id || '未提供' }}</template></el-table-column>
      <el-table-column label="结果" width="160" fixed="right"><template #default="{ row }"><el-tag :type="resultType(row.result)">{{ resultLabel(row.result) }}</el-tag></template></el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
.audit-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.audit-actions :deep(.el-button + .el-button) { margin-left: 0; }
.audit-help { color: #6b7280; font-size: 13px; }
.audit-metadata { margin: 12px 24px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
