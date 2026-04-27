import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Task } from '@/types'
import { apiTasks } from '@/api'

export const useTaskStore = defineStore('task', () => {
  const tasks = ref<Task[]>([])
  const currentTask = ref<Task | null>(null)
  const loading = ref(false)

  // 加载任务列表
  async function loadTasks(status?: string) {
    loading.value = true
    try {
      const data = await apiTasks.getAll(status, 50)
      tasks.value = data.tasks
    } catch (error) {
      console.error('Failed to load tasks:', error)
    } finally {
      loading.value = false
    }
  }

  // 获取任务详情
  async function loadTask(id: number) {
    loading.value = true
    try {
      const task = await apiTasks.get(id)
      currentTask.value = task
      return task
    } catch (error) {
      console.error('Failed to load task:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 启动更新任务
  async function startUpdate(reviewer: string = 'quant', skipFetch: boolean = false) {
    loading.value = true
    try {
      const data = await apiTasks.startUpdate(reviewer, skipFetch)
      currentTask.value = data.task
      return data
    } catch (error) {
      console.error('Failed to start update:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 取消任务
  async function cancelTask(id: number) {
    try {
      await apiTasks.cancel(id)
      // 更新本地状态
      const task = tasks.value.find((t) => t.id === id)
      if (task) {
        task.status = 'cancelled'
      }
      if (currentTask.value?.id === id) {
        currentTask.value.status = 'cancelled'
      }
    } catch (error) {
      console.error('Failed to cancel task:', error)
      throw error
    }
  }

  return {
    tasks,
    currentTask,
    loading,
    loadTasks,
    loadTask,
    startUpdate,
    cancelTask,
  }
})
