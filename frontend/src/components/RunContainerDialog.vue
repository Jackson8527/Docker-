<template>
  <el-dialog
    :model-value="modelValue"
    title="用镜像创建并运行容器"
    width="680px"
    top="5vh"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <!-- Presets: the whole point is that nobody should have to know the
         syntax for ports or env vars to get a working container. -->
    <div class="preset-box">
      <div class="preset-title">
        不会填？点一个常用镜像，自动帮你填好全部内容，直接点右下角即可
      </div>
      <div class="preset-row">
        <el-button
          v-for="p in PRESETS"
          :key="p.key"
          size="small"
          :type="activePreset === p.key ? 'primary' : 'default'"
          :plain="activePreset !== p.key"
          @click="applyPreset(p)"
        >
          {{ p.label }}
        </el-button>
        <el-button size="small" text @click="clearForm">清空</el-button>
      </div>
    </div>

    <el-form label-width="96px" label-position="right" class="run-form">
      <el-form-item label="镜像" required>
        <el-input v-model="form.image" placeholder="mysql:latest" @input="activePreset = ''" />
      </el-form-item>

      <el-form-item label="容器名">
        <el-input v-model="form.name" placeholder="选填，留空自动生成，例如 mysql-db" />
      </el-form-item>

      <el-form-item label="端口映射">
        <el-input
          v-model="form.ports"
          type="textarea"
          :rows="2"
          class="run-mono"
          placeholder="3306:3306"
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
          placeholder="mysql-data:/var/lib/mysql"
        />
        <div class="run-hint">
          每行一个，格式 <code>宿主机路径:容器路径[:ro]</code>；左侧也可以写数据卷名（会出现在「数据卷」页）
        </div>
      </el-form-item>

      <el-form-item label="启动命令">
        <el-input v-model="form.command" placeholder="选填，留空则用镜像默认命令" />
      </el-form-item>

      <el-form-item label="重启策略">
        <el-select
          v-model="form.restart_policy"
          placeholder="选填，默认不自动重启"
          clearable
          style="width: 100%"
        >
          <el-option label="always（总是重启，推荐）" value="always" />
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { containersApi, type RunContainerPayload } from '../api'
import { showApiError } from '../utils/error'

const props = defineProps<{ modelValue: boolean; image?: string }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'created'): void
}>()

const submitting = ref(false)
const activePreset = ref('')
/** Set when a preset generated a password, so the user is told what it is. */
const generatedPassword = ref('')

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

function randomPassword() {
  const chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  let out = ''
  const bytes = new Uint32Array(12)
  crypto.getRandomValues(bytes)
  for (const b of bytes) out += chars[b % chars.length]
  return out
}

interface Preset {
  key: string
  label: string
  apply: () => Partial<RunContainerPayload>
}

const PRESETS: Preset[] = [
  {
    key: 'mysql',
    label: 'MySQL',
    apply: () => {
      const pw = randomPassword()
      generatedPassword.value = pw
      return {
        image: 'mysql:latest',
        name: 'mysql-db',
        ports: '3306:3306',
        env: `MYSQL_ROOT_PASSWORD=${pw}\nTZ=Asia/Shanghai`,
        volumes: 'mysql-data:/var/lib/mysql',
        restart_policy: 'always',
      }
    },
  },
  {
    key: 'redis',
    label: 'Redis',
    apply: () => ({
      image: 'redis:latest',
      name: 'redis-cache',
      ports: '6379:6379',
      env: 'TZ=Asia/Shanghai',
      volumes: 'redis-data:/data',
      restart_policy: 'always',
    }),
  },
  {
    key: 'nginx',
    label: 'Nginx',
    apply: () => ({
      image: 'nginx:alpine',
      name: 'nginx-web',
      ports: '8080:80',
      env: 'TZ=Asia/Shanghai',
      volumes: '',
      restart_policy: 'unless-stopped',
    }),
  },
  {
    key: 'postgres',
    label: 'PostgreSQL',
    apply: () => {
      const pw = randomPassword()
      generatedPassword.value = pw
      return {
        image: 'postgres:latest',
        name: 'postgres-db',
        ports: '5432:5432',
        env: `POSTGRES_PASSWORD=${pw}\nTZ=Asia/Shanghai`,
        volumes: 'pg-data:/var/lib/postgresql/data',
        restart_policy: 'always',
      }
    },
  },
  {
    key: 'ubuntu',
    label: 'Ubuntu（只创建，用来练手）',
    apply: () => ({
      image: 'ubuntu:latest',
      name: 'ubuntu-box',
      ports: '',
      env: '',
      volumes: '',
      command: 'sleep infinity',
      restart_policy: '',
      auto_start: true,
    }),
  },
]

function clearForm() {
  form.image = ''
  form.name = ''
  form.ports = ''
  form.env = ''
  form.volumes = ''
  form.command = ''
  form.restart_policy = ''
  form.auto_start = true
  activePreset.value = ''
  generatedPassword.value = ''
}

function applyPreset(p: Preset) {
  clearForm()
  Object.assign(form, p.apply())
  activePreset.value = p.key
}

// Seed the image whenever the dialog opens, so the row's image is prefilled
// but still editable.
watch(
  () => [props.modelValue, props.image],
  ([open]) => {
    if (!open) return
    clearForm()
    form.image = props.image || ''
  },
  { immediate: true }
)

async function submit() {
  if (!form.image.trim()) {
    ElMessage.warning('请填写镜像名，或点上方常用镜像按钮自动填好')
    return
  }
  submitting.value = true
  try {
    const r = await containersApi.create({ ...form, image: form.image.trim() })
    const name = r.data?.name || ''
    emit('update:modelValue', false)
    emit('created')

    if (generatedPassword.value) {
      ElMessageBox.alert(
        `容器「${name}」已创建。\n\n` +
          `自动生成的密码：${generatedPassword.value}\n\n` +
          `请立即保存，关闭后无法再次查看（可用 docker exec 进容器重置）。`,
        '创建成功',
        { confirmButtonText: '我已保存', customStyle: { maxWidth: '520px' } }
      ).catch(() => {})
    } else {
      ElMessage.success(`容器「${name}」已创建`)
    }
  } catch (err) {
    showApiError(err, '创建容器失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.preset-box {
  background: #f8fafc;
  border: 1px solid var(--dm-border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 18px;
}

.preset-title {
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-bottom: 10px;
  line-height: 1.6;
}

.preset-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.run-form {
  max-height: 60vh;
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
