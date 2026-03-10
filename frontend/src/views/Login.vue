<template>
  <div class="login-container">
    <div class="login-card fade-in">
      <h1>📥 TG Export</h1>
      <p style="text-align: center; color: #666; margin-bottom: 30px;">
        Telegram 全功能导出工具
      </p>
      
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label">用户名</label>
          <input 
            v-model="username" 
            type="text" 
            class="form-input"
            placeholder="请输入用户名"
            required
          >
        </div>
        
        <div class="form-group">
          <label class="form-label">密码</label>
          <input 
            v-model="password" 
            type="password" 
            class="form-input"
            placeholder="请输入密码"
            required
          >
        </div>
        
        <div v-if="error" style="color: var(--danger); margin-bottom: 16px; text-align: center;">
          {{ error }}
        </div>
        
        <button type="submit" class="btn btn-primary" style="width: 100%;" :disabled="loading">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  loading.value = true
  error.value = ''
  
  try {
    const formData = new FormData()
    formData.append('username', username.value)
    formData.append('password', password.value)
    
    const response = await axios.post('/api/auth/login', formData)
    localStorage.setItem('token', response.data.access_token)
    router.push('/dashboard')
  } catch (err) {
    error.value = err.response?.data?.detail || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>


<style scoped>
.login-container {
  background: radial-gradient(1200px 800px at 15% 10%, rgba(24, 144, 255, 0.18), transparent 55%),
    radial-gradient(900px 600px at 80% 20%, rgba(82, 196, 26, 0.12), transparent 60%),
    linear-gradient(135deg, var(--sidebar-bg) 0%, #0d2137 100%);
}

.login-card {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.78);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  backdrop-filter: saturate(180%) blur(14px);
}

.login-card h1 {
  letter-spacing: 0.2px;
}

/* mobile: comfortable padding */
@media (max-width: 768px) {
  .login-card {
    margin: 0 14px;
    padding: 28px;
  }
}
</style>
