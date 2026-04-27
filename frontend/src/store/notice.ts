import { defineStore } from 'pinia'
import { ref } from 'vue'

export type GlobalNotice = {
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message: string
  actionLabel?: string
  actionRoute?: string
}

export const useNoticeStore = defineStore('notice', () => {
  const notice = ref<GlobalNotice | null>(null)

  function setNotice(next: GlobalNotice) {
    notice.value = next
  }

  function clearNotice() {
    notice.value = null
  }

  return {
    notice,
    setNotice,
    clearNotice,
  }
})
