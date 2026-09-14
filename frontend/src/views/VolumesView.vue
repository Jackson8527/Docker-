<template>
  <div>
    <div class="dm-page-head">
      <div>
        <h2 class="dm-page-title">
          卷
          <span class="dm-page-count">{{ rows.length }} 个</span>
        </h2>
      </div>
      <div class="dm-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索名称"
          :prefix-icon="Search"
          clearable
          style="width: 180px"
        />
        <el-button type="primary" :icon="Plus" @click="openCreate">创建卷</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="dm-panel">
      <el-table v-loading="loading" :data="filtered" style="width: 100%">
        <el-table-column label="名称" min-width="240">
          <template #default="{ row }">
            <span class="v-name">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="驱动" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.driver }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="挂载点" min-width="300">
          <template #default="{ row }">
            <el-tooltip :content="row.mountpoint" placement="top" :show-after="400">
              <span class="dm-mono v-mount">{{ row.mountpoint }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <!-- 150 was too narrow for 复制路径 + 删除 (156px of buttons plus the
             24px cell padding): the buttons spilled past the cell, and since
             `.dm-panel` is `overflow: hidden`, the 删除 button was cut off by
             the panel's right edge. 188 leaves the two buttons a little slack. -->
        <el-table-column label="操作" width="188" align="right" fixed="right">
          <template #default="{ row }">
            <div class="dm-row-actions">
              <el-button size="small" plain :icon="CopyDocument" @click="copyPath(row.mountpoint)">
                复制路径
              </el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="removeRow(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="v-empty">暂无数据卷</div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="showCreate" title="创建数据卷" width="420px">
      <el-form label-width="72px">
        <el-form-item label="名称">
          <el-input v-model="volName" placeholder="例如 app-data" @keyup.enter="create" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Delete, CopyDocument } from '@element-plus/icons-vue'
import { volumesApi, type VolumeRow } from '../api'
import { showApiError } from '../utils/error'

const rows = ref<VolumeRow[]>([])
const loading = ref(false)
const creating = ref(false)
const keyword = ref('')
const showCreate = ref(false)
const volName = ref('')

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return rows.value
  return rows.value.filter((r) => r.name.toLowerCase().includes(k))
})

function fail(err: unknown) {
  showApiError(err)
}

async function load() {
  loading.value = true
  try {
    const r = await volumesApi.list()
    rows.value = r.data
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  volName.value = ''
  showCreate.value = true
}

async function create() {
  const name = volName.value.trim()
  if (!name) {
    ElMessage.warning('请输入卷名称')
    return
  }
  creating.value = true
  try {
    await volumesApi.create(name)
    ElMessage.success(`已创建卷 ${name}`)
    showCreate.value = false
    load()
  } catch (err) {
    fail(err)
  } finally {
    creating.value = false
  }
}

async function copyPath(path: string) {
  try {
    await navigator.clipboard.writeText(path)
    ElMessage.success('路径已复制')
  } catch {
    ElMessage.warning('浏览器不允许访问剪贴板')
  }
}

async function removeRow(row: VolumeRow) {
  try {
    await ElMessageBox.confirm(
      `确认删除卷「${row.name}」？卷中数据将一并丢失。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await volumesApi.remove(row.name)
    ElMessage.success('已删除')
    load()
  } catch (err) {
    if (err !== 'cancel') fail(err)
  }
}

onMounted(load)
</script>

<style scoped>
.v-name {
  font-weight: 600;
  color: var(--dm-text);
}

.v-mount {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.v-empty {
  padding: 34px 0;
  color: var(--dm-text-muted);
  font-size: 13px;
}
</style>
