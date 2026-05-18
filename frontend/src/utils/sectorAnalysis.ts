export interface SectorAnalysisCatalogEntry {
  key: string
  name: string
  description: string
  policyFocus: string[]
  focusTracks: string[]
  industryHints: string[]
  enabled: boolean
  order: number
}

export interface SectorAnalysisCatalog {
  version: number
  menuTitle: string
  defaultSectorKey: string
  sectors: SectorAnalysisCatalogEntry[]
}

export interface SectorMenuEntry {
  key: string
  name: string
  path: string
  description?: string
  isOverview?: boolean
}

export interface SectorStockItem {
  code: string
  name: string
}

export type SectorStockPool = Record<string, SectorStockItem[]>

export const SECTOR_ANALYSIS_ROOT_PATH = '/sector-analysis'

export const DEFAULT_SECTOR_ANALYSIS_CATALOG: SectorAnalysisCatalog = {
  version: 1,
  menuTitle: '板块分析',
  defaultSectorKey: 'overview',
  sectors: [
    {
      key: 'ai-compute',
      name: 'AI算力与数据中心',
      description: '围绕算力扩容、传输升级、数据中心建设和配套环节展开，适合作为AI主线的核心观察池。',
      policyFocus: ['人工智能+', '智能体', '智算集群', '算电协同'],
      focusTracks: ['光模块/CPO', '高速连接', '服务器', '液冷', 'IDC', 'PCB'],
      industryHints: ['通信', '电子', '计算机设备', '数据中心'],
      enabled: true,
      order: 10,
    },
    {
      key: 'semi-storage',
      name: '半导体与先进存储',
      description: '覆盖国产替代、先进封装、HBM/存储、设备材料等方向，兼具政策确定性和业绩弹性。',
      policyFocus: ['集成电路', '国产替代', '先进封装'],
      focusTracks: ['存储', '设备', '材料', '先进封装', '模拟/算力芯片'],
      industryHints: ['半导体', '电子元件', '材料'],
      enabled: true,
      order: 20,
    },
    {
      key: 'robotics',
      name: '机器人与智能制造',
      description: '重点跟踪具身智能与工业自动化的交汇地带，优先关注核心零部件和设备环节。',
      policyFocus: ['具身智能', '智能制造', '新质生产力'],
      focusTracks: ['减速器', '伺服', '控制器', '丝杠', '传感器', '机器视觉'],
      industryHints: ['自动化设备', '专用设备', '工业控制'],
      enabled: true,
      order: 30,
    },
    {
      key: 'power-storage',
      name: '新型电力系统与储能',
      description: '相比传统发电，更聚焦电网升级、储能、算电协同与源网荷储一体化。',
      policyFocus: ['新型电力系统', '新型储能', '算电协同'],
      focusTracks: ['电网设备', '储能电池', 'PCS', '温控', '虚拟电厂', '特高压'],
      industryHints: ['电力设备', '电网自动化', '储能'],
      enabled: true,
      order: 40,
    },
    {
      key: 'strategic-materials',
      name: '战略金属与关键材料',
      description: '有色里优先看与AI、半导体、高端制造直接耦合的关键材料，而不是单纯周期金属。',
      policyFocus: ['战略资源', '关键材料', '产业链安全'],
      focusTracks: ['稀土', '钨', '镓', '铟', '锑', '铜箔', '复合材料'],
      industryHints: ['有色金属', '新材料', '稀土永磁'],
      enabled: true,
      order: 50,
    },
    {
      key: 'space-satellite',
      name: '商业航天与卫星互联网',
      description: '从政策推动走向产业化建设，适合中期跟踪卫星制造、地面设备和通信链条。',
      policyFocus: ['商业航天', '卫星互联网', '空天信息'],
      focusTracks: ['卫星制造', '地面站', '星载通信', '导航增强', '遥感应用'],
      industryHints: ['军工电子', '通信设备', '导航定位'],
      enabled: true,
      order: 60,
    },
    {
      key: 'low-altitude',
      name: '低空经济',
      description: '聚焦飞控、导航通信、核心零部件和基础设施，比泛化题材更容易形成持续跟踪池。',
      policyFocus: ['低空经济', '空域协同', '基础设施'],
      focusTracks: ['飞控', '导航通信', '航空结构件', '电驱动', '低空基建'],
      industryHints: ['通航装备', '导航通信', '航空零部件'],
      enabled: true,
      order: 70,
    },
    {
      key: 'advanced-equipment',
      name: '高端装备与海洋装备',
      description: '承接高端制造、海洋强国与大国重器主线，适合容纳船舶、能源装备、工程装备等强形态个股。',
      policyFocus: ['高端装备', '海洋强国', '重大装备'],
      focusTracks: ['船舶', '海工装备', '能源装备', '大型铸锻件', '军民融合装备'],
      industryHints: ['船舶制造', '工程机械', '高端装备'],
      enabled: true,
      order: 80,
    },
  ],
}

export const DEFAULT_SECTOR_ANALYSIS_POOL: SectorStockPool = {
  'ai-compute': [
    { code: '300308', name: '中际旭创' },
    { code: '300502', name: '新易盛' },
    { code: '688256', name: '寒武纪' },
    { code: '688008', name: '澜起科技' },
    { code: '603019', name: '中科曙光' },
    { code: '002230', name: '科大讯飞' },
    { code: '002415', name: '海康威视' },
    { code: '603501', name: '豪威集团' },
    { code: '688111', name: '金山办公' },
    { code: '000977', name: '浪潮信息' },
    { code: '300442', name: '润泽科技' },
    { code: '601138', name: '工业富联' },
  ],
  'semi-storage': [
    { code: '688041', name: '海光信息' },
    { code: '688981', name: '中芯国际' },
    { code: '002371', name: '北方华创' },
    { code: '603986', name: '兆易创新' },
    { code: '688012', name: '中微公司' },
    { code: '688072', name: '拓荆科技' },
    { code: '002049', name: '紫光国微' },
    { code: '301308', name: '江波龙' },
    { code: '688525', name: '佰维存储' },
    { code: '001309', name: '德明利' },
    { code: '603501', name: '豪威集团' },
    { code: '688008', name: '澜起科技' },
  ],
  robotics: [
    { code: '300124', name: '汇川技术' },
    { code: '601689', name: '拓普集团' },
    { code: '688017', name: '绿的谐波' },
    { code: '002472', name: '双环传动' },
    { code: '002008', name: '大族激光' },
    { code: '002230', name: '科大讯飞' },
    { code: '688777', name: '中控技术' },
    { code: '002236', name: '大华股份' },
    { code: '300024', name: '机器人' },
    { code: '002747', name: '埃斯顿' },
    { code: '002979', name: '雷赛智能' },
    { code: '603662', name: '柯力传感' },
  ],
  'power-storage': [
    { code: '300750', name: '宁德时代' },
    { code: '300274', name: '阳光电源' },
    { code: '600406', name: '国电南瑞' },
    { code: '002028', name: '思源电气' },
    { code: '600089', name: '特变电工' },
    { code: '600522', name: '中天科技' },
    { code: '600487', name: '亨通光电' },
    { code: '300014', name: '亿纬锂能' },
    { code: '601179', name: '中国西电' },
    { code: '600312', name: '平高电气' },
    { code: '601126', name: '四方股份' },
    { code: '688676', name: '金盘科技' },
  ],
  'strategic-materials': [
    { code: '600111', name: '北方稀土' },
    { code: '000831', name: '中国稀土' },
    { code: '600549', name: '厦门钨业' },
    { code: '600392', name: '盛和资源' },
    { code: '600010', name: '包钢股份' },
    { code: '601600', name: '中国铝业' },
    { code: '603799', name: '华友钴业' },
    { code: '603993', name: '洛阳钼业' },
    { code: '002738', name: '中矿资源' },
    { code: '000657', name: '中钨高新' },
    { code: '002460', name: '赣锋锂业' },
    { code: '002466', name: '天齐锂业' },
  ],
  'space-satellite': [
    { code: '600118', name: '中国卫星' },
    { code: '601698', name: '中国卫通' },
    { code: '600879', name: '航天电子' },
    { code: '600435', name: '北方导航' },
    { code: '002151', name: '北斗星通' },
    { code: '300627', name: '华测导航' },
    { code: '688568', name: '中科星图' },
    { code: '688270', name: '臻镭科技' },
    { code: '002405', name: '四维图新' },
    { code: '688375', name: '国博电子' },
    { code: '688066', name: '航天宏图' },
    { code: '300036', name: '超图软件' },
  ],
  'low-altitude': [
    { code: '002085', name: '万丰奥威' },
    { code: '300342', name: '天银机电' },
    { code: '600316', name: '洪都航空' },
    { code: '002389', name: '航天彩虹' },
    { code: '600038', name: '中直股份' },
    { code: '688297', name: '中无人机' },
    { code: '300045', name: '华力创通' },
    { code: '603308', name: '应流股份' },
    { code: '600118', name: '中国卫星' },
    { code: '600879', name: '航天电子' },
  ],
  'advanced-equipment': [
    { code: '600150', name: '中国船舶' },
    { code: '601989', name: '中国重工' },
    { code: '600482', name: '中国动力' },
    { code: '600685', name: '中船防务' },
    { code: '600072', name: '中船科技' },
    { code: '600320', name: '振华重工' },
    { code: '000880', name: '潍柴重机' },
    { code: '600764', name: '中国海防' },
    { code: '601890', name: '亚星锚链' },
    { code: '300008', name: '天海防务' },
    { code: '000425', name: '徐工机械' },
    { code: '600031', name: '三一重工' },
  ],
}

function normalizeCode(value: unknown): string {
  const digits = String(value ?? '').trim().replace(/\D/g, '')
  if (!digits) return ''
  return digits.slice(-6).padStart(6, '0')
}

function normalizeStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item ?? '').trim())
      .filter(Boolean)
  }
  if (typeof value === 'string') {
    return value
      .split(/[|,，、]/)
      .map((item) => item.trim())
      .filter(Boolean)
  }
  return []
}

function normalizePositiveInt(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : fallback
}

function normalizeCatalogEntry(value: unknown, index: number): SectorAnalysisCatalogEntry | null {
  if (!value || typeof value !== 'object') return null

  const raw = value as Record<string, unknown>
  const key = String(raw.key ?? '').trim()
  const name = String(raw.name ?? '').trim()
  const description = String(raw.description ?? '').trim()

  if (!key || !name || !description) return null

  return {
    key,
    name,
    description,
    policyFocus: normalizeStringList(raw.policyFocus),
    focusTracks: normalizeStringList(raw.focusTracks),
    industryHints: normalizeStringList(raw.industryHints),
    enabled: raw.enabled !== false,
    order: normalizePositiveInt(raw.order, (index + 1) * 10),
  }
}

function normalizeCatalogPayload(value: unknown): SectorAnalysisCatalog {
  if (!value || typeof value !== 'object') {
    return DEFAULT_SECTOR_ANALYSIS_CATALOG
  }

  const raw = value as Record<string, unknown>
  const sectors = Array.isArray(raw.sectors)
    ? raw.sectors
      .map((item, index) => normalizeCatalogEntry(item, index))
      .filter((item): item is SectorAnalysisCatalogEntry => Boolean(item && item.enabled))
      .sort((a, b) => a.order - b.order)
    : DEFAULT_SECTOR_ANALYSIS_CATALOG.sectors

  const defaultSectorKey = String(raw.defaultSectorKey ?? '').trim() || DEFAULT_SECTOR_ANALYSIS_CATALOG.defaultSectorKey

  return {
    version: normalizePositiveInt(raw.version, DEFAULT_SECTOR_ANALYSIS_CATALOG.version),
    menuTitle: String(raw.menuTitle ?? '').trim() || DEFAULT_SECTOR_ANALYSIS_CATALOG.menuTitle,
    defaultSectorKey: defaultSectorKey === 'overview' || sectors.some((item) => item.key === defaultSectorKey)
      ? defaultSectorKey
      : DEFAULT_SECTOR_ANALYSIS_CATALOG.defaultSectorKey,
    sectors: sectors.length > 0 ? sectors : DEFAULT_SECTOR_ANALYSIS_CATALOG.sectors,
  }
}

function parseJsonPayload(rawValue?: string | null): unknown {
  const text = String(rawValue ?? '').trim()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function normalizePoolRecord(payload: unknown): SectorStockPool {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return {}
  }

  const raw = payload as Record<string, unknown>
  const topKeys = Object.keys(raw)
  if (topKeys.length === 0) return {}

  const looksFlat = topKeys.every((key) => /^\d+$/.test(String(key).trim()))
  if (looksFlat) {
    return {
      当前热盘: topKeys
        .map((code) => {
          const normalizedCode = normalizeCode(code)
          const name = String(raw[code] ?? normalizedCode).trim() || normalizedCode
          return normalizedCode ? { code: normalizedCode, name } : null
        })
        .filter((item): item is SectorStockItem => Boolean(item)),
    }
  }

  const normalized: SectorStockPool = {}

  for (const [sectorKey, entries] of Object.entries(raw)) {
    const bucketKey = String(sectorKey ?? '').trim()
    if (!bucketKey) continue

    if (Array.isArray(entries)) {
      const items = entries
        .map((item) => {
          if (!item || typeof item !== 'object') return null
          const rawItem = item as Record<string, unknown>
          const code = normalizeCode(rawItem.code)
          const name = String(rawItem.name ?? code).trim() || code
          return code ? { code, name } : null
        })
        .filter((item): item is SectorStockItem => Boolean(item))
      if (items.length > 0) normalized[bucketKey] = items
      continue
    }

    if (!entries || typeof entries !== 'object') continue

    const items = Object.entries(entries as Record<string, unknown>)
      .map(([rawName, rawCode]) => {
        const nameLooksLikeCode = /^\d+$/.test(String(rawName).trim())
        const code = normalizeCode(nameLooksLikeCode ? rawName : rawCode)
        const name = nameLooksLikeCode
          ? String(rawCode ?? code).trim() || code
          : String(rawName ?? code).trim() || code
        return code ? { code, name } : null
      })
      .filter((item): item is SectorStockItem => Boolean(item))

    if (items.length > 0) normalized[bucketKey] = items
  }

  return normalized
}

export function resolveSectorAnalysisCatalog(rawValue?: string | null): SectorAnalysisCatalog {
  return normalizeCatalogPayload(parseJsonPayload(rawValue))
}

export function resolveSectorStockPool(rawValue?: string | null, fallbackRawValue?: string | null): SectorStockPool {
  const primary = normalizePoolRecord(parseJsonPayload(rawValue))
  if (Object.keys(primary).length > 0) return primary

  const fallback = normalizePoolRecord(parseJsonPayload(fallbackRawValue))
  if (Object.keys(fallback).length === 0) return DEFAULT_SECTOR_ANALYSIS_POOL

  return {
    ...DEFAULT_SECTOR_ANALYSIS_POOL,
    ...fallback,
  }
}

export function getSectorRoutePath(sectorKey?: string): string {
  const key = String(sectorKey ?? '').trim() || DEFAULT_SECTOR_ANALYSIS_CATALOG.defaultSectorKey
  return `${SECTOR_ANALYSIS_ROOT_PATH}/${key}`
}

export function buildSectorMenuEntries(catalog: SectorAnalysisCatalog): SectorMenuEntry[] {
  return [
    {
      key: catalog.defaultSectorKey,
      name: '总览',
      path: getSectorRoutePath(catalog.defaultSectorKey),
      description: '查看所有战略主题的横向总览',
      isOverview: true,
    },
    ...catalog.sectors.map((sector) => ({
      key: sector.key,
      name: sector.name,
      path: getSectorRoutePath(sector.key),
      description: sector.description,
    })),
  ]
}
