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

        <!-- The five buttons need 244px; with the 24px cell padding 326 left
             58px of dead space that pushed the six columns past the panel at
             1440 (1204 needed vs 1178 available) and made the fixed column
             slide over 创建时间. 284 keeps a small slack and lets the table fit
             at 1440; below that the fixed column behaves as before. -->
        <el-table-column label="操作" width="284" align="right" fixed="right">
          <template #default="{ row }">
            <div class="dm-row-actions">
              <el-button
                size="small"
                type="success"
                plain
                :disabled="isBusy(row) || row.state === 'running'"
                @click="act('start', row)"
              >
                启动
              </el-button>
              <el-button
                size="small"
                type="warning"
                plain
                :disabled="isBusy(row) || row.state !== 'running'"
                @click="act('stop', row)"
              >
                停止
              </el-button>

              <!-- Pause is only meaningful while running, and unpause only
                   while paused; Docker rejects both other combinations, so the
                   two states share one slot instead of two dead buttons.
                   Every other state (restarting / removing / created / dead /
                   exited) still gets a disabled placeholder: rendering nothing
                   there made the slot - and the whole feature - look missing,
                   and the row snapped back to a narrower cell. -->
              <el-button
                v-if="row.state === 'running'"
                size="small"
                type="info"
                plain
                :loading="isActing(row, 'pause')"
                :disabled="isBusy(row)"
                @click="act('pause', row)"
              >
                暂停
              </el-button>
              <el-button
                v-else-if="row.state === 'paused'"
                size="small"
                type="info"
                plain
                :loading="isActing(row, 'unpause')"
                :disabled="isBusy(row)"
                @click="act('unpause', row)"
              >
                恢复
              </el-button>
              <el-button v-else size="small" type="info" plain disabled :title="pauseHint(row)">
                暂停
              </el-button>

              <el-button size="small" plain :disabled="isBusy(row)" @click="act('restart', row)">
                重启
              </el-button>

              <el-dropdown trigger="click" @command="(cmd: string) => onMenu(cmd, row)">
                <el-button size="small" plain :icon="MoreFilled" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="logs" :icon="Document">查看日志</el-dropdown-item>
                    <!-- 进入终端 needs a live process: Docker's `exec_create`
                         blocks forever on a paused (frozen) container, so the
                         drawer would sit at 「连接中…」 with a stuck backend
                         thread. 查看日志 / 文件拷贝 stay enabled - they read the
                         log buffer and the filesystem, not the process. -->
                    <el-dropdown-item
                      command="terminal"
                      :icon="Monitor"
                      :disabled="!canOpenTerminal(row)"
                    >
                      <!-- tooltip on a plain element: el-dropdown-item's own
                           attr forwarding is not something to rely on. Kept on
                           one line so the hint never gains a stray space. -->
                      <span :title="terminalHint(row)" class="c-menu-label">进入终端<span v-if="terminalHint(row)" class="c-menu-hint">（{{ terminalHint(row) }}）</span></span>
                    </el-dropdown-item>
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
import { showApiError } from '../utils/error'
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
  showApiError(err)
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

/** Actions that take a single container id and nothing else. */
type ContainerAction = 'start' | 'stop' | 'restart' | 'pause' | 'unpause'

/** Past-tense wording for the success toast, per action. */
const ACTION_DONE: Record<ContainerAction, string> = {
  start: '启动',
  stop: '停止',
  restart: '重启',
  pause: '暂停',
  unpause: '恢复',
}

/**
 * `<id>:<action>` of the operation currently in flight; `''` when idle.
 *
 * Operations are not instantaneous: the buttons are clickable the whole time
 * the daemon is transitioning the container, and `load()` below is not awaited,
 * so `row.state` still shows the old value. Clicking twice (or clicking 停止
 * while 暂停 is still running - Docker refuses that combination) used to reach
 * the daemon mid-transition and surface as a 500.
 */
const busy = ref('')

function isBusy(row: ContainerRow): boolean {
  return busy.value.startsWith(`${row.id}:`)
}

/** Drives the spinner on the one button that was actually clicked. */
function isActing(row: ContainerRow, type: ContainerAction): boolean {
  return busy.value === `${row.id}:${type}`
}

/**
 * Tooltip for the disabled pause slot shown outside running/paused.
 *
 * `restarting` / `removing` are transient: the daemon would reject the call
 * until it settles, which is a different reason from a container that simply
 * has no process to freeze.
 */
function pauseHint(row: ContainerRow): string {
  return row.state === 'restarting' || row.state === 'removing'
    ? '容器正在过渡中，请稍候'
    : '容器未运行，无法暂停'
}

async function act(type: ContainerAction, row: ContainerRow) {
  // Re-entry guard. Kept per row so a second row can still be operated on.
  if (isBusy(row)) return
  busy.value = `${row.id}:${type}`
  try {
    await containersApi[type](row.id)
    ElMessage.success(`${row.name} 已${ACTION_DONE[type]}`)
    load()
  } catch (err) {
    fail(err)
  } finally {
    busy.value = ''
  }
}

/**
 * `true` only for a running container.
 *
 * `exec` needs a live process, and Docker's `exec_create` on a *paused*
 * (frozen) container never returns: the daemon blocks until it is unpaused, so
 * the backend's `asyncio.to_thread(exec_start, ...)` (ws.py) holds a thread and
 * the drawer sits on 「连接中…」 with nothing the user can do. A stopped
 * container simply has no process to exec into.
 *
 * 查看日志 and 文件拷贝 stay enabled in those states on purpose: they read the
 * log buffer and the container filesystem, neither of which needs the process
 * to be running (only follow-mode on a dead container ends early, which the log
 * view already reports as 「日志流已结束」).
 */
function canOpenTerminal(row: ContainerRow): boolean {
  return row.state === 'running'
}

/** Why 进入终端 is disabled, or `''` when it is available. */
function terminalHint(row: ContainerRow): string {
  if (canOpenTerminal(row)) return ''
  return row.state === 'paused' ? '容器已暂停，请先恢复' : '容器未运行，请先启动'
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
    // The call below always runs with force=true - i.e. `docker rm -f` - so the
    // prompt has to say so. A bare 「确认删除？」 reads as the safe variant, and
    // the user has no other switch in the UI that could tell them otherwise.
    await ElMessageBox.confirm(
      `确认删除容器「${row.name}」？将强制删除（等价 docker rm -f）：` +
        '运行中的容器会被立即杀死，未写入数据卷的改动不可恢复。',
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      }
    )
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

/* Reason shown next to a disabled menu entry (e.g. 进入终端 on a paused
   container). Dimmed so the entry itself still reads as the label. */
.c-menu-label {
  display: inline-block;
}
.c-menu-hint {
  color: var(--dm-text-muted);
  font-size: 12px;
}
</style>
