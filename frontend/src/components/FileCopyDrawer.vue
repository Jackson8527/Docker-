<template>
  <el-drawer :model-value="modelValue" title="文件拷贝" @update:model-value="$emit('update:modelValue', $event)">
    <el-divider content-position="left">拷入容器</el-divider>
    <el-form label-width="80px">
      <el-form-item label="目标路径">
        <el-input v-model="destPath" placeholder="/tmp" />
      </el-form-item>
      <el-form-item label="选择文件">
        <input type="file" @change="onFileChange" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :disabled="!selectedFile" @click="uploadInContainer">上传拷入</el-button>
      </el-form-item>
    </el-form>

    <el-divider>拷出容器</el-divider>
    <el-form label-width="80px">
      <el-form-item label="容器路径">
        <el-input v-model="srcPath" placeholder="/app/logs" />
      </el-form-item>
      <el-form-item>
        <el-button type="success" @click="downloadOut">下载拷出</el-button>
      </el-form-item>
    </el-form>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const props = defineProps<{ modelValue: boolean; cid: string }>()
// eslint-disable-next-line @typescript-eslint/no-unused-vars
defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const destPath = ref('/tmp')
const srcPath = ref('/')
const selectedFile = ref<File | null>(null)

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
}

async function uploadInContainer() {
  if (!selectedFile.value) return
  const fd = new FormData()
  fd.append('dest', destPath.value)
  fd.append('file', selectedFile.value)
  try {
    await axios.post(`/api/containers/${props.cid}/copy`, fd)
    ElMessage.success('已拷入容器')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || String(err))
  }
}

function downloadOut() {
  const a = document.createElement('a')
  a.href = `/api/containers/${props.cid}/copy?path=${encodeURIComponent(srcPath.value)}`
  a.download = 'container-file.tar'
  a.click()
}
</script>