<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>容器</span>
          <el-button type="primary" @click="refresh">刷新</el-button>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="image" label="镜像" />
        <el-table-column prop="state" label="状态" />
        <el-table-column prop="status" label="详情" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { containersApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const r = await containersApi.list(true)
    list.value = r.data
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>