import { computed, onMounted, onUnmounted, ref } from 'vue'

const MOBILE_MAX = 767
const TABLET_MAX = 1023

export function useResponsive() {
  const viewportWidth = ref<number>(typeof window === 'undefined' ? TABLET_MAX + 1 : window.innerWidth)

  function updateViewportWidth() {
    viewportWidth.value = window.innerWidth
  }

  onMounted(() => {
    updateViewportWidth()
    window.addEventListener('resize', updateViewportWidth, { passive: true })
    window.addEventListener('orientationchange', updateViewportWidth, { passive: true })
  })

  onUnmounted(() => {
    window.removeEventListener('resize', updateViewportWidth)
    window.removeEventListener('orientationchange', updateViewportWidth)
  })

  const isMobile = computed(() => viewportWidth.value <= MOBILE_MAX)
  const isTablet = computed(() => viewportWidth.value > MOBILE_MAX && viewportWidth.value <= TABLET_MAX)
  const isDesktop = computed(() => viewportWidth.value > TABLET_MAX)

  return {
    viewportWidth,
    isMobile,
    isTablet,
    isDesktop,
  }
}
