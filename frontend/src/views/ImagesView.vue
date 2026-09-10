<template>
  <div>
    <div class="dm-page-head">
      <div>
        <h2 class="dm-page-title">
          镜像
          <span class="dm-page-count">{{ rows.length }} 个</span>
        </h2>
      </div>
      <div class="dm-toolbar">
        <el-input
          v-model="pullName"
          placeholder="拉取镜像，如 mysql:latest"
          style="width: 230px"
          @keyup.enter="doPull"
        />
        <el-tooltip :content="mirrorHint" placement="bottom" :show-after="300">
          <el-button type="primary" :icon="Download" :loading="pulling" @click="doPull">
            拉取
          </el-button>
        </el-tooltip>
        <el-input
          v-model="keyword"
          placeholder="搜索"
          :prefix-icon="Search"
          clearable
          style="width: 180px"
        />
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="dm-panel">
      <el-table v-loading="loading" :data="filtered" style="width: 100%">
        <el-table-column label="标签" min-width="260">
          <template #default="{ row }">
            <template v-if="row.tags?.length">
              <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain" class="i-tag">
                {{ t }}
              </el-tag>
            </template>
            <span v-else class="i-none">&lt;none&gt;</span>
          </template>
        </el-table-column>

        <el-table-column label="镜像 ID" width="180">
          <template #default="{ row }">
            <span class="dm-mono">{{ shortId(row.id) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Digest" width="180">
          <template #default="{ row }">
            <span class="dm-mono">{{ shortDigest(row.digest) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="250" align="right" fixed="right">
          <template #default="{ row }">
            <div class="dm-row-actions">
              <el-button size="small" type="primary" plain :icon="VideoPlay" @click="openRun(row)">
                运行
              </el-button>
              <el-button size="small" plain :icon="Download" @click="exportImage(row)">
                导出
              </el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="removeRow(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="i-empty">
            <el-icon class="i-empty-icon"><Picture /></el-icon>
            <p>还没有镜像，先拉取一个试试</p>
          </div>
        </template>
      </el-table>
    </div>

    <RunContainerDialog v-model="showRun" :image="runImage" @created="load" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Download, Delete, Picture, VideoPlay } from '@element-plus/icons-vue'
import { imagesApi, type ImageRow } from '../api'
import { showApiError } from '../utils/error'
import RunContainerDialog from '../components/RunContainerDialog.vue'

const rows = ref<ImageRow[]>([])
const loading = ref(false)
const pulling = ref(false)
const pullName = ref('')
const keyword = ref('')
const mirrors = ref<string[]>([])
const showRun = ref(false)
const runImage = ref('')

const mirrorHint = computed(() =>
  mirrors.value.length
    ? `若 Docker Hub 不可达，将自动依次尝试镜像源：${mirrors.value.join(' → ')}，拉取成功后自动打回原名`
    : '未配置镜像源（IMAGE_MIRRORS 为空）'
)

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return rows.value
  return rows.value.filter(
    (r) => (r.tags || []).some((t) => t.toLowerCase().includes(k)) || r.id.includes(k)
  )
})

const shortId = (id: string) => (id || '').replace('sha256:', '').slice(0, 12)
const shortDigest = (d?: string) => (d || '').replace('sha256:', '').slice(0, 12) || '—'

function fail(err: unknown) {
  showApiError(err)
}

async function loadMirrors() {
  try {
    const r = await imagesApi.mirrors()
    mirrors.value = r.data?.mirrors ?? []
  } catch {
    mirrors.value = []
  }
}

async function load() {
  loading.value = true
  try {
    const r = await imagesApi.list()
    rows.value = r.data
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

async function doPull() {
  const raw = pullName.value.trim()
  if (!raw) {
    ElMessage.warning('请输入镜像名')
    return
  }
  const idx = raw.lastIndexOf(':')
  const name = idx > 0 ? raw.slice(0, idx) : raw
  const tag = idx > 0 ? raw.slice(idx + 1) : 'latest'

  pulling.value = true
  try {
    const r = await imagesApi.pull(name, tag)
    const source = r.data?.source
    const via = source && source !== 'direct' ? `（经镜像源 ${source}）` : ''
    ElMessage.success(`已拉取 ${r.data?.image || `${name}:${tag}`}${via}`)
    pullName.value = ''
    load()
  } catch (err) {
    fail(err)
  } finally {
    pulling.value = false
  }
}

function exportImage(row: ImageRow) {
  const a = document.createElement('a')
  a.href = imagesApi.saveUrl(row.id)
  a.download = `${(row.tags?.[0] || 'image').replace(/[/:]/g, '_')}.tar`
  a.click()
  ElMessage.success('已开始导出')
}

async function removeRow(row: ImageRow) {
  const label = row.tags?.[0] || shortId(row.id)
  try {
    await ElMessageBox.confirm(`确认删除镜像「${label}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await imagesApi.remove(row.id, true)
    ElMessage.success('已删除')
    load()
  } catch (err) {
    if (err !== 'cancel') fail(err)
  }
}

function openRun(row: ImageRow) {
  // Dangling images have no tag; the id works as a runnable reference.
  runImage.value = row.tags?.[0] || row.id
  showRun.value = true
}

onMounted(() => {
  load()
  loadMirrors()
})
</script>

<style scoped>
.i-tag {
  margin: 2px 6px 2px 0;
}

.i-none {
  color: var(--dm-text-muted);
  font-size: 12px;
}

.i-empty {
  padding: 34px 0;
  color: var(--dm-text-muted);
}
.i-empty-icon {
  font-size: 38px;
  color: var(--dm-border-strong);
}
.i-empty p {
  margin: 10px 0 0;
  font-size: 13px;
}
</style>
