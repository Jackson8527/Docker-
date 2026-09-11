<template>
  <div>
    <div class="dm-page-head">
      <div>
        <h2 class="dm-page-title">
          容器
          <span class="dm-page-count">{{ rows.length }} 个</span>
        </h2>
      </div>
      <div class="dm-toolbar">
        <el-input
          v-model="keyword"
          placeholder="按名称或镜像搜索"
          :prefix-icon="Search"
          clearable
          style="width: 220px"
        />
        <el-switch v-model="showAll" active-text="含已停止" @change="load" />
        <el-button type="primary" :icon="Plus" @click="openRun">新建容器</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="dm-panel">
      <el-table v-loading="loading" :data="filtered" style="width: 100%">
        <el-table-column label="状态" width="108">
          <template #default="{ row }">
            <span class="dm-dot" :class="`is-${row.state}`"></span>
            <span class="dm-state-text">{{ row.state }}</span>
          </template>
        </el-table-column>

        <el-table-column label="名称" min-width="190">
          <template #default="{ row }">
            <div class="c-name">{{ row.name }}</div>
            <div class="dm-mono">{{ shortId(row.id) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="镜像" min-width="230">
          <template #default="{ row }">
            <span class="dm-mono c-image" :title="row.image || ''">{{ row.image || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="端口" min-width="200">
          <template #default="{ row }">
            <div v-if="row.ports" class="c-ports">
              <div v-for="p in splitPorts(row.ports)" :key="p" class="dm-mono c-port">
                {{ p }}
              </div>
            </div>
            <span v-else class="c-muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">
            <span class="c-muted">{{ fmtTime(row.created) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="270" align="right" fixed="right">
          <template #default="{ row }">
            <div class="dm-row-actions">
              <el-button
                size="small"
                type="success"
                plain
                :disabled="row.state === 'running'"
                @click="act('start', row)"
              >
                启动
              </el-button>
              <el-button
                size="small"
                type="warning"
                plain
                :disabled="row.state !== 'running'"
                @click="act('stop', row)"
              >
                停止
              </el-button>
              <el-button size="small" plain @click="act('restart', row)">重启</el-button>

              <el-dropdown trigger="click" @command="(cmd: string) => onMenu(cmd, row)">
                <el-button size="small" plain :icon="MoreFilled" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="logs" :icon="Document">查看日志</el-dropdown-item>
                    <el-dropdown-item command="terminal" :icon="Monitor">进入终端</el-dropdown-item>
                    <el-dropdown-item command="copy" :icon="FolderOpened">文件拷贝</el-dropdown-item>
                    <el-dropdown-item command="commit" :icon="Box" divided>打包为镜像</el-dropdown-item>
                    <el-dropdown-item command="remove" :icon="Delete" divided>删除容器</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="c-empty">
            <el-icon class="c-empty-icon"><Box /></el-icon>
            <p>{{ showAll ? '还没有任何容器' : '没有运行中的容器' }}</p>
            <el-button v-if="!showAll" size="small" @click="((showAll = true), load())">
              显示全部容器
            </el-button>
          </div>
        </template>
      </el-table>
    </div>

    <!-- 日志 -->
    <el-drawer
      v-model="drawer.logs"
      class="dm-drawer-fill"
      size="62%"
      :title="`容器日志 · ${active?.name ?? ''}`"
      destroy-on-close
    >
      <ContainerLogs v-if="active" :name="active.name" />
    </el-drawer>

    <!-- 终端 -->
    <el-drawer
      v-model="drawer.terminal"
      class="dm-drawer-fill"
      size="72%"
      :title="`交互终端 · ${active?.name ?? ''}`"
      destroy-on-close
    >
      <ContainerTerminal v-if="active" :cid="active.id" />
    </el-drawer>

    <!-- 文件拷贝 -->
    <el-drawer
      v-model="drawer.copy"
      size="420px"
      :title="`文件拷贝 · ${active?.name ?? ''}`"
      destroy-on-close
    >
      <FileCopyDrawer v-if="active" :cid="active.id" />
    </el-drawer>

    <!-- 打包镜像 -->
    <el-dialog v-model="drawer.commit" title="打包为镜像" width="440px">
      <p class="c-dialog-hint">
        将容器当前的文件系统状态提交为一个新镜像。
      </p>
      <el-form label-width="72px">
        <el-form-item label="仓库名">
          <el-input v-model="commitRepo" placeholder="例如 myapp" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="commitTag" placeholder="latest" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawer.commit = false">取消</el-button>
        <el-button type="primary" :loading="committing" @click="doCommit">打包</el-button>
      </template>
    </el-dialog>

    <!-- 新建容器 -->
    <RunContainerDialog v-model="showRun" @created="onCreated" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search,
  Refresh,
  MoreFilled,
  Document,
  Monitor,
  FolderOpened,
  Box,
  Delete,
  Plus,
} from '@element-plus/icons-vue'
import { containersApi, type ContainerRow } from '../api'
import ContainerLogs from '../components/ContainerLogs.vue'
import ContainerTerminal from '../components/ContainerTerminal.vue'
import FileCopyDrawer from '../components/FileCopyDrawer.vue'
import RunContainerDialog from '../components/RunContainerDialog.vue'

const rows = ref<ContainerRow[]>([])
const loading = ref(false)
const keyword = ref('')
const showAll = ref(true)
const active = ref<ContainerRow | null>(null)
const showRun = ref(false)

const drawer = reactive({ logs: false, terminal: false, copy: false, commit: false })
const commitRepo = ref('')
const commitTag = ref('latest')
const committing = ref(false)

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return rows.value
  return rows.value.filter(
    (r) => r.name.toLowerCase().includes(k) || (r.image || '').toLowerCase().includes(k)
  )
})

const shortId = (id: string) => id.slice(0, 12)

/** Split '8080->80/tcp, 443->443/tcp' so each mapping gets its own line. */
function splitPorts(ports: string): string[] {
  return ports
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function fmtTime(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function fail(err: unknown) {
  const e = err as { response?: { data?: { detail?: string } } }
  ElMessage.error(e.response?.data?.detail || String(err))
}

async function load() {
  loading.value = true
  try {
    const r = await containersApi.list(showAll.value)
    rows.value = r.data
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

async function act(type: 'start' | 'stop' | 'restart', row: ContainerRow) {
  try {
    await containersApi[type](row.id)
    ElMessage.success(`${row.name} 已${type === 'start' ? '启动' : type === 'stop' ? '停止' : '重启'}`)
    load()
  } catch (err) {
    fail(err)
  }
}

function onMenu(cmd: string, row: ContainerRow) {
  active.value = row
  if (cmd === 'remove') return removeRow(row)
  if (cmd === 'commit') {
    commitRepo.value = row.name.replace(/[^a-zA-Z0-9._-]/g, '') || 'image'
    commitTag.value = 'latest'
  }
  drawer[cmd as 'logs' | 'terminal' | 'copy' | 'commit'] = true
}

async function doCommit() {
  if (!active.value || !commitRepo.value) {
    ElMessage.warning('请填写仓库名')
    return
  }
  committing.value = true
  try {
    await containersApi.commit(active.value.id, commitRepo.value, commitTag.value)
    ElMessage.success(`已打包为 ${commitRepo.value}:${commitTag.value}`)
    drawer.commit = false
  } catch (err) {
    fail(err)
  } finally {
    committing.value = false
  }
}

async function removeRow(row: ContainerRow) {
  try {
    await ElMessageBox.confirm(`确认删除容器「${row.name}」？此操作不可撤销。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await containersApi.remove(row.id, true)
    ElMessage.success('已删除')
    load()
  } catch (err) {
    if (err !== 'cancel') fail(err)
  }
}

function openRun() {
  showRun.value = true
}

function onCreated() {
  // A new container may be stopped; make sure it shows up in the list.
  showAll.value = true
  load()
}

onMounted(load)
</script>

<style scoped>
.c-name {
  font-weight: 600;
  color: var(--dm-text);
}

/* Long image names are truncated rather than broken mid-token: wrapping put
   'neo4j-gds:5.26.14-gds2.13.2' on two lines as '...:5.26.' / '14-gds2.13.2',
   which reads like the version is '5.26.'. The full name is in the title. */
.c-image {
  display: block;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* One mapping per line, and never break inside one: the previous single
   string broke mid-token, turning '127.0.0.1:17474->7474/tcp' into
   '127.0.0.1:17474-' / '>7474/tcp' and making row heights uneven. */
.c-ports {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.c-port {
  white-space: nowrap;
  color: #475569;
}

.c-muted {
  color: var(--dm-text-muted);
  font-size: 12px;
}

.c-empty {
  padding: 34px 0;
  color: var(--dm-text-muted);
}
.c-empty-icon {
  font-size: 38px;
  color: var(--dm-border-strong);
}
.c-empty p {
  margin: 10px 0 12px;
  font-size: 13px;
}

.c-dialog-hint {
  margin: 0 0 16px;
  font-size: 12px;
  color: var(--dm-text-muted);
}
</style>
