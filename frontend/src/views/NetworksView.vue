<template>
  <div>
    <div class="dm-page-head">
      <div>
        <h2 class="dm-page-title">
          网络
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
        <el-button type="primary" :icon="Plus" @click="openCreate">创建网络</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="dm-panel">
      <el-table v-loading="loading" :data="filtered" style="width: 100%">
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <span class="n-name">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="驱动" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.driver }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="范围" width="120">
          <template #default="{ row }">
            <span class="n-scope">{{ row.scope }}</span>
          </template>
        </el-table-column>

        <el-table-column label="网络 ID" min-width="180">
          <template #default="{ row }">
            <span class="dm-mono">{{ row.id.slice(0, 12) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="110" align="right" fixed="right">
          <template #default="{ row }">
            <el-tooltip
              :disabled="!isBuiltin(row.name)"
              content="Docker 内置网络不可删除"
              placement="left"
            >
              <span>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :icon="Delete"
                  :disabled="isBuiltin(row.name)"
                  @click="removeRow(row)"
                >
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>

        <template #empty>
          <div class="n-empty">暂无网络</div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="showCreate" title="创建网络" width="420px">
      <el-form label-width="72px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如 my-net" @keyup.enter="create" />
        </el-form-item>
        <el-form-item label="驱动">
          <el-select v-model="form.driver" style="width: 100%">
            <el-option label="bridge（默认）" value="bridge" />
            <el-option label="overlay" value="overlay" />
            <el-option label="macvlan" value="macvlan" />
          </el-select>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus, Delete } from '@element-plus/icons-vue'
import { networksApi, type NetworkRow } from '../api'

const BUILTIN = ['bridge', 'host', 'none']

const rows = ref<NetworkRow[]>([])
const loading = ref(false)
const creating = ref(false)
const keyword = ref('')
const showCreate = ref(false)
const form = reactive({ name: '', driver: 'bridge' })

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return rows.value
  return rows.value.filter((r) => r.name.toLowerCase().includes(k))
})

const isBuiltin = (name: string) => BUILTIN.includes(name)

function fail(err: unknown) {
  const e = err as { response?: { data?: { detail?: string } } }
  ElMessage.error(e.response?.data?.detail || String(err))
}

async function load() {
  loading.value = true
  try {
    const r = await networksApi.list()
    rows.value = r.data
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.driver = 'bridge'
  showCreate.value = true
}

async function create() {
  const name = form.name.trim()
  if (!name) {
    ElMessage.warning('请输入网络名称')
    return
  }
  creating.value = true
  try {
    await networksApi.create(name, form.driver)
    ElMessage.success(`已创建网络 ${name}`)
    showCreate.value = false
    load()
  } catch (err) {
    fail(err)
  } finally {
    creating.value = false
  }
}

async function removeRow(row: NetworkRow) {
  try {
    await ElMessageBox.confirm(`确认删除网络「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await networksApi.remove(row.id)
    ElMessage.success('已删除')
    load()
  } catch (err) {
    if (err !== 'cancel') fail(err)
  }
}

onMounted(load)
</script>

<style scoped>
.n-name {
  font-weight: 600;
  color: var(--dm-text);
}

.n-scope {
  color: var(--dm-text-muted);
  font-size: 12px;
}

.n-empty {
  padding: 34px 0;
  color: var(--dm-text-muted);
  font-size: 13px;
}
</style>
