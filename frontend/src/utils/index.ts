/**
 * 前端工具函数集合
 * 提供日期、数字、字符串等常用格式化和验证功能
 */

// ==================== 类型定义 ====================

/**
 * 评分等级类型
 */
export type ScoreLevel = 'high' | 'medium' | 'low'

/**
 * 股票涨跌状态
 */
export type ChangeStatus = 'up' | 'down' | 'neutral'

/**
 * 任务状态类型
 */
export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

/**
 * Verdict 类型
 */
export type VerdictType = 'PASS' | 'WATCH' | 'FAIL'

/**
 * 日志级别类型
 */
export type LogLevel = 'info' | 'success' | 'warning' | 'error'

// ==================== 日期格式化函数 ====================

/**
 * 格式化日期为 MM-DD 格式
 * @param dateStr - 日期字符串 (支持 YYYY-MM-DD, YYYYMMDD 等格式)
 * @returns MM/DD 格式的日期字符串
 * @example
 * formatDate('2024-01-15') // '1/15'
 * formatDate('20240115')   // '1/15'
 */
export function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) {
    return '-'
  }
  return `${d.getMonth() + 1}/${d.getDate()}`
}

/**
 * 格式化日期为 MM月DD日 格式
 * @param dateStr - 日期字符串
 * @returns MM月DD日 格式的日期字符串
 * @example
 * formatDateChinese('2024-01-15') // '1月15日'
 */
export function formatDateChinese(dateStr: string): string {
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) {
    return '-'
  }
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/**
 * 格式化日期时间为本地化字符串
 * @param dateStr - 日期时间字符串
 * @returns 本地化的日期时间字符串
 * @example
 * formatDateTime('2024-01-15T10:30:00') // '2024/1/15 10:30:00'
 */
export function formatDateTime(dateStr: string): string {
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) {
    return '-'
  }
  return d.toLocaleString('zh-CN')
}

/**
 * 格式化日期字符串，支持多种输入格式
 * @param dateStr - 日期字符串 (支持 YYYY-MM-DD 或 YYYYMMDD 格式)
 * @returns YYYY-MM-DD 格式的日期字符串
 * @example
 * formatDateString('2024-01-15') // '2024-01-15'
 * formatDateString('20240115')   // '2024-01-15'
 */
export function formatDateString(dateStr: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    return dateStr
  }
  if (/^\d{8}$/.test(dateStr)) {
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  }
  return dateStr
}

/**
 * 计算两个日期之间的时间差（秒）
 * @param start - 开始日期字符串
 * @param end - 结束日期字符串
 * @returns 时间差（秒）
 */
export function getDurationInSeconds(start: string, end: string): number {
  const startDate = new Date(start)
  const endDate = new Date(end)
  if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
    return 0
  }
  return Math.round((endDate.getTime() - startDate.getTime()) / 1000)
}

/**
 * 格式化时间持续时间为可读字符串
 * @param seconds - 秒数
 * @returns 格式化后的时间字符串
 * @example
 * formatDuration(45)      // '45秒'
 * formatDuration(125)     // '2分5秒'
 * formatDuration(3665)    // '61分5秒'
 */
export function formatDuration(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) {
    return '-'
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}秒`
  }
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.round(seconds % 60)
  return `${minutes}分${remainingSeconds}秒`
}

// ==================== 数字格式化函数 ====================

/**
 * 格式化涨跌幅为百分比字符串
 * @param pct - 涨跌幅数值
 * @returns 格式化后的百分比字符串
 * @example
 * formatChange(2.5)    // '+2.50%'
 * formatChange(-1.2)   // '-1.20%'
 * formatChange(0)      // '+0.00%'
 * formatChange(null)   // '-'
 */
export function formatChange(pct?: number | null): string {
  if (pct === undefined || pct === null || isNaN(pct)) {
    return '-'
  }
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}

/**
 * 格式化浮点数为指定小数位数的字符串
 * @param num - 数值
 * @param decimals - 小数位数，默认 2
 * @returns 格式化后的字符串
 * @example
 * formatNumber(10.5, 2)   // '10.50'
 * formatNumber(10.567, 2) // '10.57'
 * formatNumber(null)      // '-'
 */
export function formatNumber(num?: number | null, decimals: number = 2): string {
  if (num === undefined || num === null || isNaN(num)) {
    return '-'
  }
  return num.toFixed(decimals)
}

/**
 * 格式化价格，保留指定小数位
 * @param price - 价格数值
 * @param decimals - 小数位数，默认 2
 * @returns 格式化后的价格字符串
 */
export function formatPrice(price?: number | null, decimals: number = 2): string {
  return formatNumber(price, decimals)
}

/**
 * 格式化分数为字符串
 * @param score - 分数值
 * @param decimals - 小数位数，默认 1
 * @returns 格式化后的分数字符串
 */
export function formatScore(score?: number | null, decimals: number = 1): string {
  return formatNumber(score, decimals)
}

// ==================== 股票相关函数 ====================

/**
 * 格式化股票代码为标准6位格式
 * @param code - 股票代码
 * @returns 6位股票代码
 * @example
 * formatStockCode('60000')  // '060000'
 * formatStockCode('600000') // '600000'
 * formatStockCode('600036') // '600036'
 */
export function formatStockCode(code: string): string {
  const trimmed = code.trim()
  if (!/^\d+$/.test(trimmed)) {
    return trimmed
  }
  return trimmed.padStart(6, '0')
}

/**
 * 验证股票代码格式
 * @param code - 股票代码
 * @returns 是否为有效的股票代码
 */
export function isValidStockCode(code: string): boolean {
  const trimmed = code.trim()
  // 6位数字
  return /^\d{6}$/.test(trimmed)
}

/**
 * 根据股票代码判断市场
 * @param code - 股票代码
 * @returns 市场标识 'SH' | 'SZ' | 'unknown'
 */
export function getStockMarket(code: string): 'SH' | 'SZ' | 'unknown' {
  const formatted = formatStockCode(code)
  if (!/^\d{6}$/.test(formatted)) {
    return 'unknown'
  }
  // 600xxx, 601xxx, 603xxx, 688xxx 为上海市场
  if (/^(600|601|603|688)/.test(formatted)) {
    return 'SH'
  }
  // 000xxx, 001xxx, 002xxx, 003xxx, 300xxx 为深圳市场
  if (/^(000|001|002|003|300)/.test(formatted)) {
    return 'SZ'
  }
  return 'unknown'
}

/**
 * 获取股票涨跌状态
 * @param pct - 涨跌幅数值
 * @returns 涨跌状态
 */
export function getChangeStatus(pct?: number | null): ChangeStatus {
  if (pct === undefined || pct === null || isNaN(pct)) {
    return 'neutral'
  }
  if (pct > 0) return 'up'
  if (pct < 0) return 'down'
  return 'neutral'
}

// ==================== 样式和类型映射函数 ====================

/**
 * 根据分数获取 Element Plus Tag 类型
 * @param score - 分数值
 * @returns Element Plus Tag 类型
 */
export function getScoreType(score?: number | null): string {
  if (!score || isNaN(score)) return 'info'
  if (score >= 4.5) return 'success'
  if (score >= 4.0) return 'warning'
  return 'danger'
}

/**
 * 根据分数获取等级
 * @param score - 分数值
 * @returns 分数等级
 */
export function getScoreLevel(score?: number | null): ScoreLevel {
  if (!score || isNaN(score)) return 'low'
  if (score >= 4.5) return 'high'
  if (score >= 4.0) return 'medium'
  return 'low'
}

/**
 * 根据涨跌幅获取 CSS 类名
 * @param pct - 涨跌幅数值
 * @returns CSS 类名
 */
export function getChangeClass(pct?: number | null): string {
  const status = getChangeStatus(pct)
  const classMap: Record<ChangeStatus, string> = {
    up: 'text-success',
    down: 'text-danger',
    neutral: ''
  }
  return classMap[status]
}

/**
 * 根据 Verdict 值获取 Element Plus Tag 类型
 * @param verdict - Verdict 值
 * @returns Element Plus Tag 类型
 */
export function getVerdictType(verdict?: VerdictType | string): string {
  const types: Record<string, string> = {
    PASS: 'success',
    WATCH: 'warning',
    FAIL: 'danger'
  }
  return types[verdict || ''] || 'info'
}

/**
 * 根据任务状态获取 Element Plus Tag 类型
 * @param status - 任务状态
 * @returns Element Plus Tag 类型
 */
export function getStatusType(status: TaskStatus | string): string {
  const types: Record<string, string> = {
    completed: 'success',
    running: 'primary',
    failed: 'danger',
    pending: 'info',
    cancelled: 'warning'
  }
  return types[status] || 'info'
}

/**
 * 根据日志级别获取 CSS 类名
 * @param level - 日志级别
 * @returns CSS 类名
 */
export function getLogLevelClass(level: LogLevel): string {
  const classMap: Record<LogLevel, string> = {
    info: 'log-info',
    success: 'log-success',
    warning: 'log-warning',
    error: 'log-error'
  }
  return classMap[level] || 'log-info'
}

// ==================== 字符串处理函数 ====================

/**
 * 截断字符串到指定长度
 * @param str - 原字符串
 * @param maxLength - 最大长度
 * @param suffix - 截断后缀，默认 '...'
 * @returns 截断后的字符串
 */
export function truncateString(str: string, maxLength: number, suffix: string = '...'): string {
  if (!str || str.length <= maxLength) {
    return str
  }
  return str.slice(0, maxLength - suffix.length) + suffix
}

/**
 * 验证是否为有效的日期字符串
 * @param dateStr - 日期字符串
 * @returns 是否为有效日期
 */
export function isValidDateString(dateStr: string): boolean {
  const d = new Date(dateStr)
  return !isNaN(d.getTime())
}

// ==================== 进度和日志处理函数 ====================

/**
 * 从消息中解析进度百分比
 * @param message - 包含进度信息的消息
 * @returns 进度百分比 (0-100) 或 null
 * @example
 * parseProgress('步骤 1 完成')           // 10
 * parseProgress('处理中... 50%')         // 50
 * parseProgress('任务完成')              // null
 */
export function parseProgress(message: string): number | null {
  const lower = message.toLowerCase()

  // 根据步骤关键词解析
  if (message.includes('步骤 1') || lower.includes('step 1')) return 10
  if (message.includes('步骤 2') || lower.includes('step 2')) return 30
  if (message.includes('步骤 3') || lower.includes('step 3')) return 50
  if (message.includes('步骤 4') || lower.includes('step 4')) return 70
  if (message.includes('步骤 5') || lower.includes('step 5')) return 90
  if (message.includes('步骤 6') || lower.includes('step 6') || message.includes('推荐')) return 100

  // 匹配 "XX%" 格式
  const match = message.match(/(\d+)%/)
  if (match) {
    const parsed = parseInt(match[1], 10)
    if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
      return parsed
    }
  }
  return null
}

/**
 * 根据消息内容解析日志级别
 * @param message - 日志消息
 * @returns 日志级别
 */
export function parseLogType(message: string): LogLevel {
  const lower = message.toLowerCase()
  if (lower.includes('error') || lower.includes('错误') ||
      lower.includes('failed') || lower.includes('失败')) {
    return 'error'
  }
  if (lower.includes('warning') || lower.includes('警告')) {
    return 'warning'
  }
  if (lower.includes('success') || lower.includes('成功') ||
      lower.includes('completed') || lower.includes('完成')) {
    return 'success'
  }
  return 'info'
}

// ==================== URL 和 WebSocket 函数 ====================

/**
 * 构建 WebSocket URL
 * @param apiBase - API 基础 URL
 * @param path - WebSocket 路径
 * @returns WebSocket URL
 */
export function buildWebSocketUrl(apiBase: string, path: string): string {
  const wsProtocol = apiBase.startsWith('https') ? 'wss:' : 'ws:'
  const wsHost = apiBase.replace(/^https?:\/\//, '').replace(/\/.*$/, '')
  return `${wsProtocol}//${wsHost}${path}`
}

// ==================== 数组处理函数 ====================

/**
 * 数组分组
 * @param array - 原数组
 * @param keyFn - 分组键函数
 * @returns 分组后的对象
 */
export function groupBy<T>(array: T[], keyFn: (item: T) => string): Record<string, T[]> {
  return array.reduce((result, item) => {
    const key = keyFn(item)
    if (!result[key]) {
      result[key] = []
    }
    result[key].push(item)
    return result
  }, {} as Record<string, T[]>)
}

/**
 * 数组去重
 * @param array - 原数组
 * @param keyFn - 可选的键函数，用于基于对象属性去重
 * @returns 去重后的数组
 */
export function unique<T>(array: T[], keyFn?: (item: T) => any): T[] {
  if (!keyFn) {
    return [...new Set(array)]
  }
  const seen = new Set()
  return array.filter(item => {
    const key = keyFn(item)
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

/**
 * 数组排序
 * @param array - 原数组
 * @param compareFn - 比较函数
 * @returns 排序后的新数组
 */
export function sortBy<T>(array: T[], compareFn: (a: T, b: T) => number): T[] {
  return [...array].sort(compareFn)
}

// ==================== 验证函数 ====================

/**
 * 验证手机号码（中国大陆）
 * @param phone - 手机号码
 * @returns 是否有效
 */
export function isValidPhone(phone: string): boolean {
  return /^1[3-9]\d{9}$/.test(phone)
}

/**
 * 验证邮箱地址
 * @param email - 邮箱地址
 * @returns 是否有效
 */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

/**
 * 验证是否为空值
 * @param value - 待验证的值
 * @returns 是否为空
 */
export function isEmpty(value: any): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim().length === 0
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value).length === 0
  return false
}

// ==================== 默认导出 ====================

export default {
  // 日期格式化
  formatDate,
  formatDateChinese,
  formatDateTime,
  formatDateString,
  getDurationInSeconds,
  formatDuration,
  // 数字格式化
  formatChange,
  formatNumber,
  formatPrice,
  formatScore,
  // 股票相关
  formatStockCode,
  isValidStockCode,
  getStockMarket,
  getChangeStatus,
  // 样式和类型映射
  getScoreType,
  getScoreLevel,
  getChangeClass,
  getVerdictType,
  getStatusType,
  getLogLevelClass,
  // 字符串处理
  truncateString,
  isValidDateString,
  // 进度和日志
  parseProgress,
  parseLogType,
  // URL 处理
  buildWebSocketUrl,
  // 数组处理
  groupBy,
  unique,
  sortBy,
  // 验证函数
  isValidPhone,
  isValidEmail,
  isEmpty
}
