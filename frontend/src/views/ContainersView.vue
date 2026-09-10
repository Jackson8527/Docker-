<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>容器</span>
          <div>
            <el-checkbox v-model="showAll" @change="refresh">含已停止</el-checkbox>
            <el-button type="primary" @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="list" v-loading="loading" @row-dblclick="openLogs">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="image" label="镜像" />
        <el-table-column prop="state" label="状态" width="100" />
        <el-table-column prop="status" label="详情" />
        <el-table-column label="操作" width="380">
          <template #default="{ row }">
            <el-button size="small" @click="action('start', row)">启动</el-button>
            <el-button size="small" type="warning" @click="action('stop', row)">停止</el-button>
            <el-button size="small" type="info" @click="action('restart', row)">重启</el-button>
            <el-button size="small" @click="openLogs(row)">日志</el-button>
            <el-button size="small" @click="openTerminal(row)">终端</el-button>
            <el-button size="small" @click="commitDialog(row)">打包</el-button>
            <el-button size="small" @click="openCopy(row)">拷贝</el-button>
            <el-button size="small" type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 提交打包镜像对话框 -->
    <el-dialog v-model="showCommit" title="将容器打包为镜像" width="400px">
      <el-form>
        <el-form-item label="仓库">
          <el-input v-model="commitRepo" placeholder="my/image" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="commitTag" placeholder="latest" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCommit = false">取消</el-button>
        <el-button type="primary" @click="doCommit">打包</el-button>
      </template>
    </el-dialog>

    <!-- 日志抽屉 -->
    <el-drawer v-model="showLogs" title="容器日志" size="60%">
      <ContainerLogs v-if="showLogs && activeContainer" :name="activeContainer.name" />
    </el-drawer>

    <!-- 终端抽屉 -->
    <el-drawer v-model="showTerminal" title="交互终端" size="65%">
      <ContainerTerminal v-if="showTerminal && activeContainer" :cid="activeContainer.id" @close="showTerminal = false" />
    </el-drawer>

    <!-- 文件拷贝抽屉 -->
    <FileCopyDrawer v-model="showCopy" :cid="activeContainer?.id || ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { containersApi, type ContainerRow } from '../api'
import ContainerLogs from '../components/ContainerLogs.vue'
import ContainerTerminal from '../components/ContainerTerminal.vue'
import FileCopyDrawer from '../components/FileCopyDrawer.vue'

const list = ref<ContainerRow[]>([])
const loading = ref(false)
const showAll = ref(false)
const activeContainer = ref<ContainerRow | null>(null)

const showCommit = ref(false)
const commitContainer = ref<ContainerRow | null>(null)
const commitRepo = ref('')
const commitTag = ref('latest')
const showLogs = ref(false)
const showTerminal = ref(false)
const showCopy = ref(false)

async function refresh() {
  loading.value = true
  try {
    const r = await containersApi.list(showAll.value)
    list.value = r.data
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  } finally {
    loading.value = false
  }
}

async function action(type: string, row: ContainerRow) {
  try {
    await (containersApi as any)[type](row.id)
    ElMessage.success('操作成功')
    refresh()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

function openLogs(row: ContainerRow) {
  activeContainer.value = row
  showLogs.value = true
}

function openTerminal(row: ContainerRow) {
  activeContainer.value = row
  showTerminal.value = true
}

function commitDialog(row: ContainerRow) {
  commitContainer.value = row
  commitRepo.value = ''
  commitTag.value = 'latest'
  showCommit.value = true
}

async function doCommit() {
  if (!commitRepo.value) {
    ElMessage.warning('请填写仓库名')
    return
  }
  try {
    await containersApi.commit(commitContainer.value!.id, commitRepo.value, commitTag.value)
    ElMessage.success('已打包为镜像')
    showCommit.value = false
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

function openCopy(row: ContainerRow) {
  activeContainer.value = row
  showCopy.value = true
}

async function removeRow(row: ContainerRow) {
  try {
    await ElMessageBox.confirm(`确认删除容器 ${row.name}？`, '删除确认', { type: 'warning' })
    await containersApi.remove(row.id, true)
    ElMessage.success('已删除')
    refresh()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err.response?.data?.detail || String(err))
  }
}

onMounted(refresh)
</script>