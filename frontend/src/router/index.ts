import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/store/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/tomorrow-star',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', guestOnly: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { title: '注册', guestOnly: true },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/views/Profile.vue'),
    meta: { title: '个人资料', requiresAuth: true },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/Admin.vue'),
    meta: { title: '用户管理', requiresAuth: true, requiresAdmin: true },
  },
  {
    path: '/config',
    name: 'Config',
    component: () => import('@/views/Config.vue'),
    meta: { title: '配置管理', icon: 'Setting', requiresAuth: true },
  },
  {
    path: '/update',
    name: 'Update',
    component: () => import('@/views/Update.vue'),
    meta: { title: '运维管理', icon: 'Refresh', requiresAuth: true },
  },
  {
    path: '/tomorrow-star',
    name: 'TomorrowStar',
    component: () => import('@/views/TomorrowStar.vue'),
    meta: { title: '明日之星', icon: 'Star', keepAlive: true, requiresAuth: true },
  },
  {
    path: '/diagnosis',
    name: 'Diagnosis',
    component: () => import('@/views/Diagnosis.vue'),
    meta: { title: '单股诊断', icon: 'Search', keepAlive: true, requiresAuth: true },
  },
  {
    path: '/watchlist',
    name: 'Watchlist',
    component: () => import('@/views/Watchlist.vue'),
    meta: { title: '重点观察', icon: 'View', keepAlive: true, requiresAuth: true },
  },
  {
    path: '/system-info',
    name: 'SystemInfo',
    component: () => import('@/views/SystemInfo.vue'),
    meta: { title: '系统说明', icon: 'Document', requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  document.title = `${to.meta.title || 'StockTrader'} - StockTrader 2.0`

  // 动态导入 auth store 避免循环依赖
  const authStore = useAuthStore()

  // 首次加载时尝试获取用户信息
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }

  const isAuthenticated = authStore.isAuthenticated

  // 需要认证的路由
  if (to.meta.requiresAuth && !isAuthenticated) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 管理员路由
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next('/')
    return
  }

  // 仅限游客的路由（登录/注册页）
  if (to.meta.guestOnly && isAuthenticated) {
    next('/')
    return
  }

  next()
})

export default router
