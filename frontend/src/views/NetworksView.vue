<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>网络</span>
          <div>
            <el-button type="primary" @click="showCreate = true">创建网络</el-button>
            <el-button @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="driver" label="驱动" />
        <el-table-column prop="scope" label="范围" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="创建网络" width="400px">
      <el-form>
        <el-form-item label="名称"><el-input v-model="netName" /></el-form-item>
        <el-form-item label="驱动"><el-input v-model="netDriver" placeholder="bridge" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="createNet">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { networksApi } from '../api'

const list = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const netName = ref('')
const netDriver = ref('bridge')

async function refresh() {
  loading.value = true
  try {
    const r = await networksApi.list()
    list.value = r.data
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  } finally {
    loading.value = false
  }
}

async function createNet() {
  if (!netName.value) return
  try {
    await networksApi.create(netName.value, netDriver.value || 'bridge')
    ElMessage.success('已创建')
    showCreate.value = false
    netName.value = ''
    refresh()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

async function removeRow(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除网络 ${row.name}？`, '删除确认', { type: 'warning' })
    await networksApi.remove(row.id)
    ElMessage.success('已删除')
    refresh()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err.response?.data?.detail || String(err))
  }
}

onMounted(refresh)
</script>