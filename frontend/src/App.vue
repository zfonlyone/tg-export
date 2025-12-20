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
            <span class="icon">📊</span>
            <span>仪表盘</span>
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
      <router-view />
    </main>
  </div>
  
  <!-- 未登录时直接显示路由 -->
  <router-view v-else />
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const isLoggedIn = computed(() => {
  return !!localStorage.getItem('token')
})

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>
