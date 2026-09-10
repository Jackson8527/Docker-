<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>镜像</span>
          <el-button type="primary" @click="refresh">刷新</el-button>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="id" label="ID" width="120" />
        <el-table-column label="标签"><template #default="{ row }">{{ (row.tags || []).join(', ') }}</template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { imagesApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const r = await imagesApi.list()
    list.value = r.data
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>