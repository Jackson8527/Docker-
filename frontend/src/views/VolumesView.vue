<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>卷</span>
          <div>
            <el-button type="primary" @click="showCreate = true">创建卷</el-button>
            <el-button @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="driver" label="驱动" />
        <el-table-column prop="mountpoint" label="挂载点" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="创建卷" width="400px">
      <el-form>
        <el-form-item label="名称"><el-input v-model="volName" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="createVol">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { volumesApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const volName = ref('')

async function refresh() {
  loading.value = true
  try {
    const r = await volumesApi.list()
    list.value = r.data
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  } finally {
    loading.value = false
  }
}

async function createVol() {
  if (!volName.value) return
  try {
    await volumesApi.create(volName.value)
    ElMessage.success('已创建')
    showCreate.value = false
    volName.value = ''
    refresh()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

async function removeRow(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除卷 ${row.name}？`, '删除确认', { type: 'warning' })
    await volumesApi.remove(row.name)
    ElMessage.success('已删除')
    refresh()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err.response?.data?.detail || String(err))
  }
}

onMounted(refresh)
</script>