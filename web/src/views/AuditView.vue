<script setup lang="ts">
defineProps<{
  audits: Array<Record<string, unknown>>;
}>();
</script>

<template>
  <section>
    <el-table :data="audits" border>
      <el-table-column prop="occurred_at" label="时间" min-width="190" />
      <el-table-column prop="action" label="动作" min-width="180" />
      <el-table-column prop="actor_type" label="操作者" width="110" />
      <el-table-column prop="result" label="结果" width="100" />
    </el-table>
  </section>
</template>
