<template>
  <div v-if="isLoggedIn" class="app-container">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-logo">
        <h1>📥 TG Export</h1>
      </div>
      <ul class="sidebar-nav">
        <li>
          <router-link to="/dashboard" active-class="active">
            <span class="icon">🏠</span>
            <span>首页</span>
          </router-link>
        </li>
        <li>
          <router-link to="/export" active-class="active">
            <span class="icon">📥</span>
            <span>导出数据</span>
          </router-link>
        </li>
        <li>
          <router-link to="/tasks" active-class="active">
            <span class="icon">📋</span>
            <span>任务管理</span>
          </router-link>
        </li>
        <li>
          <router-link to="/settings" active-class="active">
            <span class="icon">⚙️</span>
            <span>设置</span>
          </router-link>
        </li>
      </ul>
      <div style="padding: 20px; margin-top: auto; border-top: 1px solid var(--border);">
        <button @click="logout" class="btn btn-outline" style="width: 100%;">
          🚪 退出登录
        </button>
      </div>
    </aside>
    
    <!-- 主内容 -->
    <main class="main-content">
      <!-- 顶部导航栏 -->
      <div class="top-bar" v-if="showBackButton">
        <button @click="goBack" class="btn btn-outline btn-sm">
          ← 返回
        </button>
        <router-link to="/dashboard" class="btn btn-outline btn-sm" style="margin-left: 10px;">
          🏠 首页
        </router-link>
      </div>
      <router-view />
    </main>
  </div>
  
  <!-- 未登录时直接显示路由 -->
  <router-view v-else />
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const isLoggedIn = computed(() => {
  return !!localStorage.getItem('token')
})

// 在非首页显示返回按钮
const showBackButton = computed(() => {
  return route.path !== '/dashboard' && route.path !== '/'
})

function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/dashboard')
  }
}

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>

<style scoped>
.top-bar {
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--border);
}

.btn-sm {
  padding: 6px 12px;
  font-size: 13px;
}
</style>
