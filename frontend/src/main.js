import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'

// 路由配置
const routes = [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', component: () => import('./views/Login.vue') },
    { path: '/dashboard', component: () => import('./views/Dashboard.vue'), meta: { requiresAuth: true } },
    { path: '/export', component: () => import('./views/Export.vue'), meta: { requiresAuth: true } },
    { path: '/tasks', component: () => import('./views/Tasks.vue'), meta: { requiresAuth: true } },
    { path: '/settings', component: () => import('./views/Settings.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({
    history: createWebHistory(),
    routes,
})

// 路由守卫
router.beforeEach((to, from, next) => {
    const token = localStorage.getItem('token')
    if (to.meta.requiresAuth && !token) {
        next('/login')
    } else {
        next()
    }
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
