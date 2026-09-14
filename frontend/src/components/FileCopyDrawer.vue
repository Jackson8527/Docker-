<template>
  <div class="copy-wrap">
    <section class="copy-section">
      <div class="copy-title">
        <el-icon><UploadFilled /></el-icon>
        <span>从本机拷入容器</span>
      </div>
      <p class="copy-hint">
        文件会以 tar 形式写入容器的目标目录，目标目录必须已存在。
      </p>

      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        :file-list="fileList"
        :on-change="onFileChange"
        :on-remove="onFileRemove"
      >
        <el-icon class="copy-upload-icon"><UploadFilled /></el-icon>
        <div class="copy-upload-text">拖拽文件到此处，或 <em>点击选择</em></div>
      </el-upload>

      <div class="copy-field">
        <label>容器内目标路径</label>
        <el-input v-model="destPath" placeholder="/tmp">
          <template #prepend>目录</template>
        </el-input>
      </div>

      <el-button
        type="primary"
        :loading="uploading"
        :disabled="!file"
        class="copy-submit"
        @click="upload"
      >
        {{ uploading ? '上传中…' : '开始拷贝' }}
      </el-button>
    </section>

    <el-divider />

    <section class="copy-section">
      <div class="copy-title">
        <el-icon><Download /></el-icon>
        <span>从容器拷出到本机</span>
      </div>
      <p class="copy-hint">
        输入容器内的文件或目录路径，浏览器会下载打包后的 tar 文件。
      </p>

      <div class="copy-field">
        <label>容器内路径</label>
        <el-input v-model="srcPath" placeholder="/app/logs" />
      </div>

      <el-button type="success" class="copy-submit" :loading="downloading" @click="download">
        下载
      </el-button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Download } from '@element-plus/icons-vue'
import type { UploadFile, UploadFiles } from 'element-plus'
import axios from 'axios'
import { startDownload } from '../utils/download'

const props = defineProps<{ cid: string }>()

const destPath = ref('/tmp')
const srcPath = ref('/')
const file = ref<File | null>(null)
const fileList = ref<UploadFiles>([])
const uploading = ref(false)
const downloading = ref(false)

function onFileChange(uploadFile: UploadFile, uploadFiles: UploadFiles) {
  // el-upload keeps every selection; only the newest one is copied.
  fileList.value = uploadFiles.slice(-1)
  file.value = (uploadFile.raw as File) ?? null
}

function onFileRemove() {
  file.value = null
  fileList.value = []
}

async function upload() {
  if (!file.value) return
  const fd = new FormData()
  fd.append('dest', destPath.value)
  fd.append('file', file.value)

  uploading.value = true
  try {
    await axios.post(`/api/containers/${props.cid}/copy`, fd)
    ElMessage.success(`已拷入 ${destPath.value}`)
    file.value = null
    fileList.value = []
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    ElMessage.error(e.response?.data?.detail || String(err))
  } finally {
    uploading.value = false
  }
}

async function download() {
  if (!srcPath.value) {
    ElMessage.warning('请填写容器内路径')
    return
  }
  const url = `/api/containers/${props.cid}/copy?path=${encodeURIComponent(srcPath.value)}`
  downloading.value = true
  try {
    // Preflight first: a bare <a href> reports nothing, so a 500 (path missing,
    // container gone) used to surface as "已开始下载" plus a JSON error page.
    if (await startDownload(url, 'container-file.tar')) {
      ElMessage.success('已开始下载')
    }
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.copy-wrap {
  padding: 18px 20px;
  overflow-y: auto;
  height: 100%;
}

.copy-section {
  margin-bottom: 6px;
}

.copy-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--dm-text);
  margin-bottom: 6px;
}

.copy-hint {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--dm-text-muted);
  line-height: 1.6;
}

.copy-upload-icon {
  font-size: 40px;
  color: var(--dm-border-strong);
  margin-bottom: 6px;
}

.copy-upload-text {
  font-size: 13px;
  color: var(--dm-text-muted);
}
.copy-upload-text em {
  color: var(--dm-primary);
  font-style: normal;
}

.copy-field {
  margin: 16px 0;
}
.copy-field label {
  display: block;
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-bottom: 6px;
}

.copy-submit {
  width: 100%;
}
</style>
