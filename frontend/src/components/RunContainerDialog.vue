<template>
  <el-dialog
    :model-value="modelValue"
    title="用镜像创建并运行容器"
    width="620px"
    top="6vh"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-form label-width="96px" label-position="right" class="run-form">
      <el-form-item label="镜像" required>
        <el-input v-model="form.image" placeholder="mysql:latest" />
      </el-form-item>

      <el-form-item label="容器名">
        <el-input v-model="form.name" placeholder="留空则自动生成，例如 mysql-db" />
      </el-form-item>

      <el-form-item label="端口映射">
        <el-input
          v-model="form.ports"
          type="textarea"
          :rows="2"
          class="run-mono"
          placeholder="3306:3306&#10;8080:80"
        />
        <div class="run-hint">
          每行一个，格式 <code>宿主机端口:容器端口</code>；写 <code>127.0.0.1:8080:80</code>
          可只绑定本机；<code>53:53/udp</code> 指定协议
        </div>
      </el-form-item>

      <el-form-item label="环境变量">
        <el-input
          v-model="form.env"
          type="textarea"
          :rows="3"
          class="run-mono"
          placeholder="MYSQL_ROOT_PASSWORD=yourpassword&#10;TZ=Asia/Shanghai"
        />
        <div class="run-hint">每行一个，格式 <code>KEY=VALUE</code></div>
      </el-form-item>

      <el-form-item label="目录挂载">
        <el-input
          v-model="form.volumes"
          type="textarea"
          :rows="2"
          class="run-mono"
          placeholder="/data/mysql:/var/lib/mysql&#10;app-data:/var/lib/app:ro"
        />
        <div class="run-hint">
          每行一个，格式 <code>宿主机路径:容器路径[:ro]</code>；左侧也可以写已存在的数据卷名
        </div>
      </el-form-item>

      <el-form-item label="启动命令">
        <el-input v-model="form.command" placeholder="留空则用镜像默认命令" />
      </el-form-item>

      <el-form-item label="重启策略">
        <el-select v-model="form.restart_policy" style="width: 100%">
          <el-option label="不设置" value="" />
          <el-option label="always（总是重启）" value="always" />
          <el-option label="unless-stopped（手动停止后不重启）" value="unless-stopped" />
          <el-option label="on-failure（异常退出才重启）" value="on-failure" />
          <el-option label="no（从不重启）" value="no" />
        </el-select>
      </el-form-item>

      <el-form-item label="立即启动">
        <el-switch v-model="form.auto_start" />
        <span class="run-hint run-hint-inline">
          {{ form.auto_start ? '创建后立即运行' : '只创建，稍后手动启动' }}
        </span>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ form.auto_start ? '创建并启动' : '仅创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { containersApi, type RunContainerPayload } from '../api'
import { showApiError } from '../utils/error'

const props = defineProps<{ modelValue: boolean; image?: string }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'created'): void
}>()

const submitting = ref(false)

const form = reactive<RunContainerPayload>({
  image: '',
  name: '',
  ports: '',
  env: '',
  volumes: '',
  command: '',
  restart_policy: '',
  auto_start: true,
})

// Seed the image whenever the dialog opens, so the row's image is prefilled
// but still editable.
watch(
  () => [props.modelValue, props.image],
  ([open]) => {
    if (!open) return
    form.image = props.image || ''
    form.name = ''
    form.ports = ''
    form.env = ''
    form.volumes = ''
    form.command = ''
    form.restart_policy = ''
    form.auto_start = true
  },
  { immediate: true }
)

async function submit() {
  if (!form.image.trim()) {
    ElMessage.warning('请填写镜像名')
    return
  }
  submitting.value = true
  try {
    const r = await containersApi.create({ ...form, image: form.image.trim() })
    ElMessage.success(`容器 ${r.data?.name || ''} 已创建`)
    emit('update:modelValue', false)
    emit('created')
  } catch (err) {
    showApiError(err, '创建容器失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.run-form {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 6px;
}

.run-mono :deep(textarea) {
  font-family: var(--dm-mono);
  font-size: 12px;
}

.run-hint {
  font-size: 11px;
  color: var(--dm-text-muted);
  line-height: 1.7;
  margin-top: 4px;
}

.run-hint-inline {
  margin: 0 0 0 12px;
}

.run-hint code {
  background: #f1f5f9;
  border: 1px solid var(--dm-border);
  border-radius: 3px;
  padding: 0 4px;
  font-family: var(--dm-mono);
  color: #475569;
}
</style>
