<template>
  <div class="fade-in settings-page">
    <div class="page-header settings-header">
      <div>
        <div class="eyebrow">Configuration</div>
        <h1>⚙️ 设置</h1>
        <p class="subtitle">管理 Telegram API 凭证与账号登录方式。桌面端看全貌，移动端也能顺着步骤完成配置。</p>
      </div>
      <div class="settings-status-pill" :class="{ connected: telegramStatus.authorized }">
        {{ telegramStatus.authorized ? '已连接 Telegram' : '未连接 Telegram' }}
      </div>
    </div>

    <div class="settings-shell">
      <aside class="settings-rail card">
        <div class="rail-block">
          <div class="eyebrow">API</div>
          <h3>配置摘要</h3>
          <div class="summary-stack">
            <div class="summary-item">
              <span class="label">API 凭证</span>
              <span class="value">{{ hasApiConfig ? '已保存' : '未配置' }}</span>
            </div>
            <div class="summary-item">
              <span class="label">登录状态</span>
              <span class="value">{{ telegramStatus.authorized ? '已登录 Telegram' : '未登录' }}</span>
            </div>
            <div class="summary-item" v-if="telegramStatus.user?.id">
              <span class="label">当前账号</span>
              <span class="value">{{ telegramStatus.user?.first_name || 'Telegram 用户' }}</span>
            </div>
          </div>
        </div>

        <div class="rail-block tip-block">
          <div class="eyebrow">Guide</div>
          <h4>推荐顺序</h4>
          <ol class="tip-list">
            <li>先保存 API ID / API Hash</li>
            <li>再选择手机号或扫码登录</li>
            <li>如果启用了两步验证，再补密码</li>
          </ol>
        </div>

        <div v-if="message" class="message-box" :class="messageType">
          {{ message }}
        </div>
      </aside>

      <section class="settings-main">
        <div class="card feature-card">
          <div class="card-header feature-head">
            <div>
              <div class="eyebrow">Telegram App API</div>
              <h2>🔗 Telegram App API</h2>
            </div>
            <span class="feature-badge" :class="{ ready: hasApiConfig }">{{ hasApiConfig ? '已配置' : '待配置' }}</span>
          </div>

          <p class="helper-text">
            从 <a href="https://my.telegram.org/apps" target="_blank" style="color: var(--primary);">my.telegram.org</a>
            获取应用 API 凭证（仅需配置一次）。
          </p>

          <div class="api-grid">
            <div class="form-group compact-group">
              <label class="form-label">API ID</label>
              <input v-model="apiId" type="number" class="form-input" placeholder="例如: 12345678" :disabled="hasApiConfig && !editingApi">
            </div>
            <div class="form-group compact-group">
              <label class="form-label">API Hash</label>
              <input v-model="apiHash" type="text" class="form-input" :placeholder="hasApiConfig && !editingApi ? '******' : '例如: abcdef1234567890...'" :disabled="hasApiConfig && !editingApi">
            </div>
          </div>

          <div class="action-row">
            <button v-if="!hasApiConfig || editingApi" @click="saveApiConfig" class="btn btn-primary" :disabled="!apiId || (!apiHash && !hasApiConfig) || loading">
              {{ loading ? '保存中...' : '保存配置' }}
            </button>
            <button v-if="hasApiConfig && !editingApi" @click="editingApi = true" class="btn btn-outline">修改配置</button>
            <button v-if="editingApi" @click="cancelEditApi" class="btn btn-outline">取消</button>
          </div>

          <div v-if="hasApiConfig && !editingApi" class="success-inline">✅ API 已保存至服务器（环境变量）</div>
        </div>

        <div class="card feature-card">
          <div class="card-header feature-head">
            <div>
              <div class="eyebrow">Login</div>
              <h2>📱 Telegram 账号登录</h2>
            </div>
            <span class="feature-badge" :class="{ ready: telegramStatus.authorized }">{{ telegramStatus.authorized ? '已连接' : '待登录' }}</span>
          </div>

          <div v-if="telegramStatus.authorized" class="connected-panel">
            <div class="connected-user">
              <div class="avatar-bubble">{{ telegramStatus.user?.first_name?.[0] || '?' }}</div>
              <div class="account-copy">
                <div class="name">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
                <div class="handle">@{{ telegramStatus.user?.username || 'N/A' }}</div>
                <div class="id">ID: {{ telegramStatus.user?.id }}</div>
              </div>
              <span class="status-badge status-completed">已连接</span>
            </div>

            <button @click="disconnectTelegram" class="btn btn-outline danger-outline">🚪 断开连接</button>
          </div>

          <div v-else class="login-layout">
            <div class="login-mode-switch">
              <button class="switch-btn" :class="{ active: loginMode === 'phone' }" @click="switchLoginMode('phone')">手机号登录</button>
              <button class="switch-btn" :class="{ active: loginMode === 'qr' }" @click="switchLoginMode('qr')">扫码登录</button>
            </div>

            <div v-if="loginMode === 'qr'" class="qr-layout">
              <div class="qr-card">
                <p class="helper-text center-text">在 Telegram App 中打开「设置 → 设备 → 连接桌面设备」扫描下方二维码</p>
                <div class="qr-frame">
                  <img v-if="qrImageDataUrl" :src="qrImageDataUrl" alt="Telegram QR Login" class="qr-image">
                  <span v-else class="qr-placeholder">点击“生成二维码”开始扫码登录</span>
                  <div v-if="qrScannedOverlay" class="qr-overlay">已扫码，等待验证</div>
                </div>
                <div class="action-row centered-row">
                  <button @click="startQrLogin" class="btn btn-primary" :disabled="loading">
                    {{ loading ? '生成中...' : (qrImageDataUrl ? '刷新二维码' : '生成二维码') }}
                  </button>
                  <button class="btn btn-outline" @click="showQrPasswordInput" :disabled="!qrImageDataUrl">已扫码，输入2FA</button>
                  <button class="btn btn-outline" @click="switchLoginMode('phone')">改用手机号</button>
                </div>
              </div>

              <div v-if="qrPasswordRequired" class="card soft-panel inline-card">
                <p class="helper-text">扫码成功，请输入 Telegram 两步验证密码完成登录。</p>
                <div class="form-group compact-group">
                  <label class="form-label">两步验证密码</label>
                  <input v-model="qrPassword" type="password" class="form-input" placeholder="输入两步验证密码" @keyup.enter="submitQrPassword">
                </div>
                <button @click="submitQrPassword" class="btn btn-primary" :disabled="!qrPassword || loading">
                  {{ loading ? '验证中...' : '确认登录' }}
                </button>
              </div>
            </div>

            <template v-if="loginMode === 'phone'">
              <div class="phone-stepper">
                <div :class="['login-step', loginStep >= 1 ? 'active' : '']">1. 手机号</div>
                <div :class="['login-step', loginStep >= 2 ? 'active' : '']">2. 验证码</div>
                <div :class="['login-step', loginStep >= 3 ? 'active' : '']">3. 二次验证</div>
                <div :class="['login-step', loginStep >= 4 ? 'active' : '']">4. 完成</div>
              </div>

              <div v-if="loginStep === 1" class="card soft-panel inline-card">
                <p class="helper-text">输入您的 Telegram 手机号码（含国际区号）。</p>
                <div class="form-group compact-group">
                  <label class="form-label">手机号码</label>
                  <input v-model="phone" type="tel" class="form-input" placeholder="+86 138xxxxxxxx">
                </div>
                <button @click="sendCode" class="btn btn-primary" :disabled="!phone || loading">{{ loading ? '发送中...' : '发送验证码' }}</button>
              </div>

              <div v-if="loginStep === 2" class="card soft-panel inline-card">
                <p class="helper-text">验证码已发送到您的 Telegram 应用，请查收。</p>
                <div class="form-group compact-group">
                  <label class="form-label">验证码</label>
                  <input v-model="code" type="text" class="form-input" placeholder="输入5位验证码" maxlength="5">
                </div>
                <div class="action-row">
                  <button @click="loginStep = 1" class="btn btn-outline">← 上一步</button>
                  <button @click="signIn" class="btn btn-primary" :disabled="!code || loading">{{ loading ? '验证中...' : '验证登录' }}</button>
                </div>
              </div>

              <div v-if="loginStep === 3" class="card soft-panel inline-card">
                <p class="helper-text">您的账号已启用两步验证，请输入密码。</p>
                <div class="form-group compact-group">
                  <label class="form-label">两步验证密码</label>
                  <input v-model="password" type="password" class="form-input" placeholder="输入两步验证密码" @keyup.enter="signIn">
                </div>
                <div class="action-row">
                  <button @click="loginStep = 2" class="btn btn-outline">← 上一步</button>
                  <button @click="signIn" class="btn btn-primary" :disabled="!password || loading">{{ loading ? '验证中...' : '确认登录' }}</button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </section>
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
const loading = ref(false)
const telegramStatus = ref({ authorized: false, user: null })
const loginStep = ref(1)
const loginMode = ref('phone')
const message = ref('')
const messageType = ref('success')
const editingApi = ref(false)
const hasApiConfig = ref(false)
const botSaved = ref(false)
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
    await axios.post('/api/telegram/init', {
      api_id: Number(apiId.value),
      api_hash: apiHash.value
    }, { headers: getAuthHeader() })
    editingApi.value = false
    hasApiConfig.value = true
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
    const res = await axios.post('/api/telegram/send-code', { phone: phone.value }, { headers: getAuthHeader() })
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
    }, { headers: getAuthHeader() })
    showMessage('🎉 登录成功!', 'success')
    loginStep.value = 4
    await fetchStatus()
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    if ((err.response?.status === 403 || err.response?.status === 401) && (detail === 'SESSION_PASSWORD_NEEDED' || detail.includes('2FA') || detail.includes('password'))) {
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
  if (mode !== 'qr') stopQrPolling()
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
      const res = await axios.post('/api/telegram/qr/status', { token_id: qrTokenId.value }, { headers: getAuthHeader() })
      if (res.data.status === 'authorized') {
        stopQrPolling()
        loginStep.value = 4
        showMessage('🎉 扫码登录成功!', 'success')
        await fetchStatus()
      } else if (res.data.status === 'pending' && res.data.refresh && res.data.login_url) {
        if (res.data.token_id) qrTokenId.value = res.data.token_id
        qrLoginUrl.value = res.data.login_url
        qrImageDataUrl.value = await QRCode.toDataURL(qrLoginUrl.value, { width: 260, margin: 1 })
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
      showMessage('二维码状态轮询失败: ' + (err.response?.data?.detail || err.message), 'error')
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
    qrImageDataUrl.value = await QRCode.toDataURL(qrLoginUrl.value, { width: 260, margin: 1 })
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
onUnmounted(() => stopQrPolling())
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 18px; }
.settings-header { align-items: flex-start; gap: 16px; margin-bottom: 0; }
.eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--primary-dark); font-weight: 700; margin-bottom: 6px; }
.subtitle, .helper-text { color: #64748b; }
.settings-status-pill { padding: 8px 14px; border-radius: 999px; background: rgba(255,255,255,0.65); color: #475569; font-weight: 800; border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
.settings-status-pill.connected { background: #dcfce7; color: #166534; }
.settings-shell { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 20px; align-items: start; }
.settings-rail { position: sticky; top: 20px; display: flex; flex-direction: column; gap: 16px; }
.rail-block { display: flex; flex-direction: column; gap: 12px; }
.summary-stack { display: flex; flex-direction: column; gap: 10px; }
.summary-item { display: flex; flex-direction: column; gap: 2px; }
.summary-item .label { color: #64748b; font-size: 12px; }
.summary-item .value { font-weight: 700; }
.tip-block { background: rgba(255,255,255,0.55); border-radius: 18px; padding: 14px; border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
.tip-list { padding-left: 18px; color: #475569; display: flex; flex-direction: column; gap: 8px; }
.message-box { padding: 12px 14px; border-radius: 14px; font-weight: 600; }
.message-box.success { background: #ecfdf3; color: #166534; }
.message-box.error { background: #fff1f2; color: #be123c; }
.settings-main { display: flex; flex-direction: column; gap: 18px; }
.feature-card { padding: 24px; border-radius: 24px; background: rgba(255,255,255,0.82); border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: 0 18px 40px -26px rgba(15,23,42,0.35); }
.feature-head { align-items: flex-start; }
.feature-badge { padding: 6px 10px; border-radius: 999px; background: #fef3c7; color: #92400e; font-size: 12px; font-weight: 700; }
.feature-badge.ready { background: #dcfce7; color: #166534; }
.api-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 16px; margin-top: 16px; }
.compact-group { margin-bottom: 0; }
.action-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
.centered-row { justify-content: center; }
.success-inline { margin-top: 10px; color: #16a34a; font-size: 13px; }
.connected-panel { display: flex; flex-direction: column; gap: 16px; }
.connected-user { display: flex; align-items: center; gap: 16px; padding: 16px; background: rgba(34,197,94,0.10); border-radius: 18px; border: 1px solid rgba(34,197,94,0.18); }
.avatar-bubble { width: 54px; height: 54px; border-radius: 50%; background: linear-gradient(135deg, var(--primary), #8b5cf6); color: white; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 800; }
.account-copy { flex: 1; }
.account-copy .name { font-weight: 800; }
.account-copy .handle { color: #475569; }
.account-copy .id { font-size: 12px; color: #94a3b8; }
.danger-outline { color: var(--danger); border-color: var(--danger); }
.login-layout { display: flex; flex-direction: column; gap: 18px; }
.login-mode-switch { display: inline-flex; gap: 6px; background: rgba(255,255,255,0.55); padding: 6px; border-radius: 16px; width: fit-content; border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
.switch-btn { border: none; background: transparent; padding: 10px 14px; border-radius: 14px; cursor: pointer; font-weight: 800; transition: transform 0.12s ease, background 0.18s ease, box-shadow 0.18s ease; }
.switch-btn:active { transform: scale(0.99); }
.switch-btn.active { background: white; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.qr-layout { display: flex; flex-direction: column; gap: 16px; }
.qr-card { display: flex; flex-direction: column; gap: 14px; align-items: center; }
.center-text { text-align: center; }
.qr-frame { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 280px; height: 280px; border: 1px solid rgba(17,24,39,0.10); border-radius: 22px; background: rgba(255,255,255,0.82); overflow: hidden; -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: 0 18px 40px -28px rgba(15,23,42,0.38); }
.qr-image { max-width: 260px; max-height: 260px; }
.qr-placeholder { color: #94a3b8; font-size: 13px; }
.qr-overlay { position: absolute; inset: 0; background: rgba(34, 197, 94, 0.35); display: flex; align-items: center; justify-content: center; color: #14532d; font-weight: 700; font-size: 16px; }
.inline-card { padding: 18px; border-radius: 22px; margin-bottom: 0; background: rgba(255,255,255,0.82); border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: 0 18px 40px -30px rgba(15,23,42,0.32); }
.phone-stepper { display: flex; gap: 10px; flex-wrap: wrap; }
.login-step { padding: 8px 14px; background: rgba(255,255,255,0.60); border: 1px solid rgba(17,24,39,0.08); border-radius: 999px; color: #64748b; font-size: 12px; font-weight: 800; white-space: nowrap; -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
.login-step.active { background: var(--primary); color: white; }
@media (max-width: 1024px) { .settings-shell { grid-template-columns: 1fr; } .settings-rail { position: static; } }
@media (max-width: 768px) { .api-grid { grid-template-columns: 1fr; } .settings-header, .feature-head, .connected-user { flex-direction: column; align-items: stretch; } .login-mode-switch { width: 100%; } .switch-btn { flex: 1; } .qr-frame { width: 100%; max-width: 280px; } }
</style>
