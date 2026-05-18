import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SECTOR_ANALYSIS_CATALOG,
  DEFAULT_SECTOR_ANALYSIS_POOL,
  buildSectorMenuEntries,
  getSectorRoutePath,
  resolveSectorAnalysisCatalog,
  resolveSectorStockPool,
} from '@/utils/sectorAnalysis'

describe('sectorAnalysis utils', () => {
  it('falls back to default catalog when config is empty', () => {
    const catalog = resolveSectorAnalysisCatalog('')

    expect(catalog.menuTitle).toBe('板块分析')
    expect(catalog.defaultSectorKey).toBe('overview')
    expect(catalog.sectors.length).toBe(DEFAULT_SECTOR_ANALYSIS_CATALOG.sectors.length)
  })

  it('normalizes custom catalog and builds menu entries', () => {
    const catalog = resolveSectorAnalysisCatalog(JSON.stringify({
      version: 2,
      menuTitle: '战略主题',
      defaultSectorKey: 'overview',
      sectors: [
        {
          key: 'robotics',
          name: '机器人',
          description: '测试说明',
          policyFocus: ['具身智能'],
          focusTracks: ['减速器'],
          industryHints: ['自动化设备'],
          order: 30,
        },
      ],
    }))
    const entries = buildSectorMenuEntries(catalog)

    expect(catalog.menuTitle).toBe('战略主题')
    expect(entries.map((item) => item.path)).toEqual([
      getSectorRoutePath('overview'),
      getSectorRoutePath('robotics'),
    ])
  })

  it('parses grouped pool config and prefers explicit sector pool', () => {
    const pool = resolveSectorStockPool(JSON.stringify({
      robotics: {
        埃斯顿: '002747',
        绿的谐波: '688017',
      },
    }))

    expect(pool.robotics).toEqual([
      { code: '002747', name: '埃斯顿' },
      { code: '688017', name: '绿的谐波' },
    ])
  })

  it('falls back to built-in default pool when sector pool config is empty', () => {
    const pool = resolveSectorStockPool('', '')

    expect(pool['ai-compute']).toEqual(DEFAULT_SECTOR_ANALYSIS_POOL['ai-compute'])
    expect(pool['advanced-equipment']).toEqual(DEFAULT_SECTOR_ANALYSIS_POOL['advanced-equipment'])
  })

  it('merges fallback pool on top of built-in default pool', () => {
    const pool = resolveSectorStockPool('', JSON.stringify({
      robotics: {
        埃斯顿: '002747',
      },
    }))

    expect(pool.robotics).toEqual([{ code: '002747', name: '埃斯顿' }])
    expect(pool['ai-compute']).toEqual(DEFAULT_SECTOR_ANALYSIS_POOL['ai-compute'])
  })
})
