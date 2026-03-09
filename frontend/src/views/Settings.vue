<template>
  <div class="fade-in">
    <h1 style="margin-bottom: 20px;">⚙️ 设置</h1>

    <div class="card">
      <div class="card-header">
        <h2>🔗 Telegram App API</h2>
      </div>

      <p style="color: #666; margin-bottom: 15px;">
        从 <a href="https://my.telegram.org/apps" target="_blank" style="color: var(--primary);">my.telegram.org</a>
        获取应用 API 凭证（仅需配置一次）
      </p>

      <div style="display: flex; gap: 15px; align-items: flex-end;">
        <div class="form-group" style="flex: 1; margin-bottom: 0;">
          <label class="form-label">API ID</label>
          <input v-model="apiId" type="number" class="form-input" placeholder="例如: 12345678" :disabled="hasApiConfig && !editingApi">
        </div>
        <div class="form-group" style="flex: 2; margin-bottom: 0;">
          <label class="form-label">API Hash</label>
          <input v-model="apiHash" type="text" class="form-input" :placeholder="hasApiConfig && !editingApi ? '******' : '例如: abcdef1234567890...'" :disabled="hasApiConfig && !editingApi">
        </div>
        <div style="display: flex; gap: 10px;">
          <button v-if="!hasApiConfig || editingApi" @click="saveApiConfig" class="btn btn-primary" :disabled="!apiId || (!apiHash && !hasApiConfig) || loading" style="white-space: nowrap;">
            {{ loading ? '保存中...' : '保存配置' }}
          </button>
          <button v-if="hasApiConfig && !editingApi" @click="editingApi = true" class="btn btn-outline" style="white-space: nowrap;">
            修改配置
          </button>
          <button v-if="editingApi" @click="cancelEditApi" class="btn btn-outline" style="white-space: nowrap;">
            取消
          </button>
        </div>
      </div>
      <div v-if="hasApiConfig && !editingApi" style="margin-top: 10px; color: #28a745; font-size: 13px;">
        ✅ API 已保存至服务器 (环境变量)
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2>📱 Telegram 账号登录</h2>
      </div>

      <div v-if="telegramStatus.authorized">
        <div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: #d4edda; border-radius: 8px; margin-bottom: 15px;">
          <div style="width: 50px; height: 50px; background: var(--primary); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 24px;">
            {{ telegramStatus.user?.first_name?.[0] || '?' }}
          </div>
          <div style="flex: 1;">
            <div style="font-weight: 600; font-size: 16px;">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
            <div style="color: #666;">@{{ telegramStatus.user?.username || 'N/A' }}</div>
            <div style="color: #999; font-size: 12px;">ID: {{ telegramStatus.user?.id }}</div>
          </div>
          <span class="status-badge status-completed">已连接</span>
        </div>

        <button @click="disconnectTelegram" class="btn btn-outline" style="color: var(--danger); border-color: var(--danger);">
          🚪 断开连接
        </button>
      </div>

      <div v-else>
        <div style="display: flex; gap: 10px; margin-bottom: 16px;">
          <button class="btn" :class="loginMode === 'phone' ? 'btn-primary' : 'btn-outline'" @click="switchLoginMode('phone')">手机号登录</button>
          <button class="btn" :class="loginMode === 'qr' ? 'btn-primary' : 'btn-outline'" @click="switchLoginMode('qr')">扫码登录</button>
        </div>

        <div v-if="loginMode === 'qr'" style="text-align: center; padding: 10px 0 6px;">
          <p style="color: #666; margin-bottom: 12px;">
            在 Telegram App 中打开「设置 -> 设备 -> 连接桌面设备」扫描下方二维码
          </p>
          <div style="position: relative; display: inline-flex; align-items: center; justify-content: center; width: 280px; height: 280px; border: 1px solid #eee; border-radius: 10px; background: #fff; overflow: hidden;">
            <img v-if="qrImageDataUrl" :src="qrImageDataUrl" alt="Telegram QR Login" style="max-width: 260px; max-height: 260px;">
            <span v-else style="color: #999; font-size: 13px;">点击“生成二维码”开始扫码登录</span>
            <div v-if="qrScannedOverlay" style="position: absolute; inset: 0; background: rgba(34, 197, 94, 0.35); display: flex; align-items: center; justify-content: center; color: #14532d; font-weight: 700; font-size: 16px; pointer-events: none;">
              已扫码，等待验证
            </div>
          </div>
          <div style="margin-top: 12px; display: flex; justify-content: center; gap: 10px;">
            <button @click="startQrLogin" class="btn btn-primary" :disabled="loading">
              {{ loading ? '生成中...' : (qrImageDataUrl ? '刷新二维码' : '生成二维码') }}
            </button>
            <button class="btn btn-outline" @click="showQrPasswordInput" :disabled="!qrImageDataUrl">已扫码，输入2FA</button>
            <button class="btn btn-outline" @click="switchLoginMode('phone')">改用手机号</button>
          </div>

          <div v-if="qrPasswordRequired" style="max-width: 420px; margin: 14px auto 0; text-align: left;">
            <p style="color: #666; margin-bottom: 8px;">扫码成功，请输入 Telegram 两步验证密码完成登录</p>
            <div class="form-group" style="margin-bottom: 10px;">
              <label class="form-label">两步验证密码</label>
              <input v-model="qrPassword" type="password" class="form-input" placeholder="输入两步验证密码" @keyup.enter="submitQrPassword">
            </div>
            <button @click="submitQrPassword" class="btn btn-primary" :disabled="!qrPassword || loading">
              {{ loading ? '验证中...' : '确认登录' }}
            </button>
          </div>
        </div>

        <template v-if="loginMode === 'phone'">
        <div style="display: flex; gap: 10px; margin-bottom: 20px;">
          <div :class="['login-step', loginStep >= 1 ? 'active' : '']">1. 手机号</div>
          <div :class="['login-step', loginStep >= 2 ? 'active' : '']">2. 验证码</div>
          <div :class="['login-step', loginStep >= 3 ? 'active' : '']">3. 二次验证</div>
          <div :class="['login-step', loginStep >= 4 ? 'active' : '']">4. 完成</div>
        </div>

        <div v-if="loginStep === 1">
          <p style="color: #666; margin-bottom: 15px;">输入您的 Telegram 手机号码（含国际区号）</p>
          <div class="form-group">
            <label class="form-label">手机号码</label>
            <input v-model="phone" type="tel" class="form-input" placeholder="+86 138xxxxxxxx">
          </div>
          <button @click="sendCode" class="btn btn-primary" :disabled="!phone || loading">{{ loading ? '发送中...' : '发送验证码' }}</button>
        </div>

        <div v-if="loginStep === 2">
          <p style="color: #666; margin-bottom: 15px;">验证码已发送到您的 Telegram 应用，请查收</p>
          <div class="form-group">
            <label class="form-label">验证码</label>
            <input v-model="code" type="text" class="form-input" placeholder="输入5位验证码" maxlength="5">
          </div>
          <div style="display: flex; gap: 10px;">
            <button @click="loginStep = 1" class="btn btn-outline">← 上一步</button>
            <button @click="signIn" class="btn btn-primary" :disabled="!code || loading">{{ loading ? '验证中...' : '验证登录' }}</button>
          </div>
        </div>

        <div v-if="loginStep === 3">
          <p style="color: #666; margin-bottom: 15px;">您的账号已启用两步验证，请输入密码</p>
          <div class="form-group">
            <label class="form-label">两步验证密码</label>
            <input v-model="password" type="password" class="form-input" placeholder="输入两步验证密码" @keyup.enter="signIn">
          </div>
          <div style="display: flex; gap: 10px;">
            <button @click="loginStep = 2" class="btn btn-outline">← 上一步</button>
            <button @click="signIn" class="btn btn-primary" :disabled="!password || loading">{{ loading ? '验证中...' : '确认登录' }}</button>
          </div>
        </div>
        </template>
      </div>

      <div v-if="message" :style="{ color: messageType === 'error' ? 'var(--danger)' : 'var(--success)', marginTop: '15px', padding: '10px', borderRadius: '6px', background: messageType === 'error' ? '#fee' : '#efe' }">
        {{ message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import QRCode from 'qrcode'

const router = useRouter()
const apiId = ref('')
const apiHash = ref('')
const phone = ref('')
const code = ref('')
const password = ref('')
const phoneCodeHash = ref('')
const botToken = ref('')
const exportPath = ref('/downloads')
const maxConcurrent = ref(5)
const loading = ref(false)
const telegramStatus = ref({ authorized: false, user: null })
const loginStep = ref(1)
const loginMode = ref('phone')
const message = ref('')
const messageType = ref('success')
const editingApi = ref(false)
const hasApiConfig = ref(false)
const botSaved = ref(false)
const savingBot = ref(false)
const qrTokenId = ref('')
const qrLoginUrl = ref('')
const qrImageDataUrl = ref('')
const qrPasswordRequired = ref(false)
const qrPassword = ref('')
const qrScannedOverlay = ref(false)
let qrPollingTimer = null

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function fetchStatus() {
  try {
    const [statusRes, settingsRes] = await Promise.all([
      axios.get('/api/telegram/status', { headers: getAuthHeader() }),
      axios.get('/api/settings', { headers: getAuthHeader() })
    ])
    telegramStatus.value = statusRes.data
    hasApiConfig.value = settingsRes.data.has_api_config || false
    if (settingsRes.data.api_id) apiId.value = settingsRes.data.api_id
    exportPath.value = settingsRes.data.export_path || '/downloads'
    maxConcurrent.value = settingsRes.data.max_concurrent_downloads || 5
    botSaved.value = settingsRes.data.has_bot_token || false
  } catch (err) {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      router.push('/login')
    }
    console.error('获取设置失败:', err)
  }
}

function cancelEditApi() {
  editingApi.value = false
  apiHash.value = ''
}

async function saveApiConfig() {
  loading.value = true
  try {
    await axios.post(`/api/telegram/init?api_id=${apiId.value}&api_hash=${apiHash.value}`, {}, { headers: getAuthHeader() })
    editingApi.value = false
    showMessage('API 配置已保存', 'success')
  } catch (err) {
    showMessage('配置失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

async function sendCode() {
  loading.value = true
  try {
    const res = await axios.post('/api/telegram/send-code', {
      phone: phone.value
    }, { headers: getAuthHeader() })
    phoneCodeHash.value = res.data.phone_code_hash
    loginStep.value = 2
    showMessage('验证码已发送，请查看 Telegram 应用', 'success')
  } catch (err) {
    showMessage('发送失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

async function signIn() {
  loading.value = true
  try {
    await axios.post('/api/telegram/sign-in', {
      phone: phone.value,
      code: code.value,
      phone_code_hash: phoneCodeHash.value,
      password: password.value || undefined
    }, {
      headers: getAuthHeader()
    })
    showMessage('🎉 登录成功!', 'success')
    loginStep.value = 4
    await fetchStatus()
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    if ((err.response?.status === 403 || err.response?.status === 401) &&
        (detail === 'SESSION_PASSWORD_NEEDED' || detail.includes('2FA') || detail.includes('password'))) {
      loginStep.value = 3
      showMessage('请提供两步验证密码 (Cloud Password)', 'success')
    } else {
      showMessage('登录失败: ' + detail, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function disconnectTelegram() {
  if (!confirm('确定要断开 Telegram 连接吗？')) return
  try {
    await axios.post('/api/telegram/disconnect', {}, { headers: getAuthHeader() })
    telegramStatus.value = { authorized: false, user: null }
    loginStep.value = 1
    stopQrPolling()
    showMessage('已断开连接', 'success')
  } catch (err) {
    showMessage('断开失败: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

function stopQrPolling() {
  if (qrPollingTimer) {
    clearInterval(qrPollingTimer)
    qrPollingTimer = null
  }
}

function switchLoginMode(mode) {
  loginMode.value = mode
  if (mode !== 'qr') {
    stopQrPolling()
  }
  qrPasswordRequired.value = false
  qrPassword.value = ''
}

function showQrPasswordInput() {
  if (!qrImageDataUrl.value) return
  qrPasswordRequired.value = true
  stopQrPolling()
}

function startQrPolling() {
  stopQrPolling()
  if (!qrTokenId.value) return

  qrPollingTimer = setInterval(async () => {
    if (qrPasswordRequired.value) {
      stopQrPolling()
      return
    }
    try {
      const res = await axios.post('/api/telegram/qr/status', {
        token_id: qrTokenId.value
      }, {
        headers: getAuthHeader()
      })
      if (res.data.status === 'authorized') {
        stopQrPolling()
        loginStep.value = 4
        showMessage('🎉 扫码登录成功!', 'success')
        await fetchStatus()
      } else if (res.data.status === 'pending' && res.data.refresh && res.data.login_url) {
        if (res.data.token_id) {
          qrTokenId.value = res.data.token_id
        }
        qrLoginUrl.value = res.data.login_url
        qrImageDataUrl.value = await QRCode.toDataURL(qrLoginUrl.value, {
          width: 260,
          margin: 1
        })
      } else if (res.data.status === 'password_required') {
        stopQrPolling()
        qrPasswordRequired.value = true
        showMessage('该账号开启了两步验证，请输入密码完成登录', 'error')
      } else if (res.data.status === 'expired') {
        stopQrPolling()
        showMessage(res.data.message || '二维码已过期，请刷新', 'error')
      }
    } catch (err) {
      stopQrPolling()
      const detail = err.response?.data?.detail || err.message
      showMessage('二维码状态轮询失败: ' + detail, 'error')
      console.error('二维码状态轮询失败:', err)
    }
  }, 2000)
}

async function startQrLogin() {
  loading.value = true
  try {
    const res = await axios.post('/api/telegram/qr/start', {}, { headers: getAuthHeader() })
    if (res.data.status === 'authorized') {
      loginStep.value = 4
      showMessage('🎉 登录成功!', 'success')
      await fetchStatus()
      return
    }

    qrTokenId.value = res.data.token_id
    qrLoginUrl.value = res.data.login_url
    qrPasswordRequired.value = false
    qrPassword.value = ''
    qrImageDataUrl.value = await QRCode.toDataURL(qrLoginUrl.value, {
      width: 260,
      margin: 1
    })
    switchLoginMode('qr')
    startQrPolling()
    showMessage('请在 Telegram App 中扫描二维码并确认登录', 'success')
  } catch (err) {
    showMessage('二维码登录初始化失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

async function submitQrPassword() {
  if (!qrPassword.value) {
    showMessage('请输入两步验证密码', 'error')
    return
  }
  loading.value = true
  try {
    const res = await axios.post('/api/telegram/qr/password', { password: qrPassword.value }, { headers: getAuthHeader() })
    if (res.data.status === 'authorized') {
      qrPasswordRequired.value = false
      qrPassword.value = ''
      loginStep.value = 4
      showMessage('🎉 登录成功!', 'success')
      await fetchStatus()
      return
    }
    showMessage('验证未完成，请重试', 'error')
  } catch (err) {
    showMessage('密码验证失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

function showMessage(msg, type) {
  message.value = msg
  messageType.value = type
  setTimeout(() => { message.value = '' }, 5000)
}

onMounted(fetchStatus)
onUnmounted(() => {
  stopQrPolling()
})
</script>

<style scoped>
.login-step {
  padding: 8px 16px;
  background: var(--border);
  border-radius: 20px;
  color: #666;
  font-size: 13px;
  white-space: nowrap;
}

.login-step.active {
  background: var(--primary);
  color: white;
}
</style>
