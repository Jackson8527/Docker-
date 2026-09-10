<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>网络</span>
          <el-button type="primary" @click="refresh">刷新</el-button>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="driver" label="驱动" />
        <el-table-column prop="scope" label="范围" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { networksApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const r = await networksApi.list()
    list.value = r.data
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>