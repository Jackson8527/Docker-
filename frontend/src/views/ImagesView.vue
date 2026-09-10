<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>镜像</span>
          <div>
            <el-input v-model="pullName" placeholder="仓库:标签" style="width: 200px" />
            <el-button type="primary" @click="doPull">拉取</el-button>
            <el-button @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="id" label="ID" width="120" />
        <el-table-column label="标签">
          <template #default="{ row }">{{ (row.tags || []).join(', ') || '&lt;none&gt;' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="exportImage(row)">导出</el-button>
            <el-button size="small" type="danger" @click="removeImage(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { imagesApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)
const pullName = ref('')

async function refresh() {
  loading.value = true
  try {
    const r = await imagesApi.list()
    list.value = r.data
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  } finally {
    loading.value = false
  }
}

async function doPull() {
  if (!pullName.value) return
  const [name, tag] = pullName.value.split(':')
  try {
    await imagesApi.pull(name, tag || 'latest')
    ElMessage.success('拉取成功')
    pullName.value = ''
    refresh()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

function exportImage(row: any) {
  const a = document.createElement('a')
  a.href = imagesApi.saveUrl(row.id)
  a.download = 'image.tar'
  a.click()
}

async function removeImage(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除镜像 ${row.id}？`, '删除确认', { type: 'warning' })
    await imagesApi.remove(row.id, true)
    ElMessage.success('已删除')
    refresh()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err.response?.data?.detail || String(err))
  }
}

onMounted(refresh)
</script>