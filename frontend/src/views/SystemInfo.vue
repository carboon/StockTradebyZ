<template>
  <div class="system-info-page">
    <el-alert
      class="risk-alert"
      title="风险提示"
      type="warning"
      :closable="false"
      show-icon
    >
      <p>本系统用于技术筛选与复核，不构成投资建议。</p>
      <p>所有结果均基于历史行情与规则判断，无法覆盖政策、公告与突发事件风险。</p>
      <p>PASS 也不等于可直接买入，仍需结合仓位、止损与市场环境处理。</p>
    </el-alert>

    <div class="page-grid">
      <div class="summary-column">
        <el-card class="hero-card">
          <template #header>
            <div class="section-header">
              <span>系统说明</span>
              <el-tag type="info" effect="plain">当前默认口径：B1 + Quant</el-tag>
            </div>
          </template>

          <div class="hero-content">
            <h2>筛候选，做复核，给结论。</h2>
            <p>系统默认围绕 <span class="hero-highlight">低位启动 + 趋势健康度</span> 工作，不直接做全市场盲打分。</p>
          </div>
        </el-card>

        <div class="overview-grid">
          <el-card class="overview-card">
            <div class="overview-label">流动性池</div>
            <div class="overview-value">Top 2000</div>
            <p>按近 43 个交易日滚动成交额排序，只保留活跃股票。</p>
          </el-card>

          <el-card class="overview-card">
            <div class="overview-label">B1 候选</div>
            <div class="overview-value">4 个条件</div>
            <p>四项同时通过，才进入候选池。</p>
          </el-card>

          <el-card class="overview-card">
            <div class="overview-label">四维复核</div>
            <div class="overview-value">4 个维度</div>
            <p>趋势结构、价格位置、量价行为、历史异动，逐项复核后再给结论。</p>
          </el-card>

          <el-card class="overview-card">
            <div class="overview-label">最终结论</div>
            <div class="overview-value">3 档</div>
            <p>输出 PASS / WATCH / FAIL，不只看总分。</p>
          </el-card>

          <el-card class="overview-card coming-soon">
            <template #default>
              <div class="coming-soon-content">
                <el-tooltip content="待完善：当前不纳入正式流程，仅保留概念位。" placement="top">
                  <div class="overview-label">LLM 评分（待完善）</div>
                </el-tooltip>
                <div class="overview-value">
                  <el-tooltip content="待完善：当前不纳入正式流程，仅保留概念位。" placement="top">
                    <span>—</span>
                  </el-tooltip>
                </div>
                <p>基于大语言模型的智能分析与评分。</p>
              </div>
            </template>
          </el-card>
        </div>
      </div>

      <div class="detail-column">
        <el-card class="tabs-card">
          <el-tabs v-model="activeTab" class="info-tabs">
            <el-tab-pane label="使用方式" name="usage">
              <div class="panel-section">
                <h3>推荐使用顺序</h3>
                <div class="usage-list">
                  <div class="usage-item">
                    <div class="usage-step">1</div>
                    <div>
                      <strong>先看明日之星</strong>
                      <p>查看指定交易日的候选股与分析结果，优先锁定系统已经完成复核的股票。</p>
                    </div>
                  </div>
                  <div class="usage-item">
                    <div class="usage-step">2</div>
                    <div>
                      <strong>再进单股诊断</strong>
                      <p>对单只股票补看 K 线、B1 细项、评分细项与历史检查结果。</p>
                    </div>
                  </div>
                  <div class="usage-item">
                    <div class="usage-step">3</div>
                    <div>
                      <strong>最后放入重点观察</strong>
                      <p>对准备跟踪或已持仓的股票，记录成本、仓位，并查看操作建议。</p>
                    </div>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>页面分工</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag type="primary">明日之星</el-tag>
                    <p>看指定交易日的候选股、分析结果和历史快照。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag type="success">单股诊断</el-tag>
                    <p>看某只股票当前或指定日期的独立检查结果，不等同于候选池结果。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag type="warning">重点观察</el-tag>
                    <p>看自选跟踪、持仓信息与操作建议，偏执行层。</p>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="名词解释" name="terms">
              <div class="panel-section">
                <h3>核心名词</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag effect="plain">流动性池</el-tag>
                    <p>全市场先按滚动成交额排序，取前 2000 只股票，作为基础观察范围。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">候选股</el-tag>
                    <p>通过 B1 四项检查的股票，属于“可进入下一步复核”的集合。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">分析结果</el-tag>
                    <p>候选股经过前置过滤与四维评分后的结论输出。</p>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>两套判断体系</h3>
                <div class="logic-card">
                  <strong>B1 检查</strong>
                  <p>用于筛选低位启动机会，重点看价格位置与基础结构。</p>
                </div>
                <div class="logic-card">
                  <strong>量化评分</strong>
                  <p>用于评估趋势健康度，重点看趋势延续性，不要求与 B1 结果完全一致。</p>
                </div>
              </div>

              <div class="panel-section">
                <h3>结论含义</h3>
                <div class="verdict-list">
                  <div class="verdict-item pass">
                    <div class="verdict-title">PASS</div>
                    <p>更接近趋势启动，且总分与关键条件同时达标。</p>
                  </div>
                  <div class="verdict-item watch">
                    <div class="verdict-title">WATCH</div>
                    <p>结构偏多，但更像反弹延续、确认不足或强度不够。</p>
                  </div>
                  <div class="verdict-item fail">
                    <div class="verdict-title">FAIL</div>
                    <p>当前位置或风险结构不合适，当前不进入推荐结果。</p>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="详细名词解释" name="glossary">
              <div class="panel-section">
                <h3>数据与来源</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag effect="plain">Tushare</el-tag>
                    <p>本系统主要的数据源，用于拉取 A 股行情、行业分类、指数、解禁与基础资料。系统中的候选筛选、前置过滤和部分状态检查依赖这些数据。</p>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>B1 候选条件</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag effect="plain">KDJ 低位</el-tag>
                    <p>当前默认看 KDJ 的 J 值，满足以下任一条件即可：J 小于 15，或 J 落在该股票自身历史较低分位（默认前 10%）附近。目的不是找最强，而是优先找相对偏低、可能刚启动的位置。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">知行线结构</el-tag>
                    <p>当前默认使用 14、28、57、114 日四条均线构成长期结构线，并配合 10 日双重平滑得到短线。默认要求收盘价高于长期结构线，且短线高于长期结构线，也就是“价格不在长期线下方，短线也已站回长期结构之上”。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">周线多头</el-tag>
                    <p>当前默认把日线聚合成周线后，检查 10 周、20 周、30 周均线是否满足短期线 &gt; 中期线 &gt; 长期线。只有周线结构仍偏多，系统才认为这不是单纯的日线级别弱反弹。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">最大量日非阴线</el-tag>
                    <p>当前默认回看最近 20 个交易日，找出成交量最大的一天，并检查那一天是否满足收盘价不低于开盘价。这样做是为了避免把“巨量长阴、放量派发”也当成健康启动信号。</p>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>前置过滤项</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag effect="plain">ST</el-tag>
                    <p>股票名称带 ST 或 *ST，通常意味着经营、财务或合规风险更高，系统默认直接过滤。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">次新</el-tag>
                    <p>上市时间较短、历史样本不足的股票。当前默认要求至少积累一定交易日数据后才允许进入复核。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">解禁</el-tag>
                    <p>未来一段时间若有较大比例限售股解禁，可能带来额外抛压，因此系统会按解禁占自由流通比例做过滤。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">行业强度</el-tag>
                    <p>当前默认看近 20 个交易日表现：先计算股票所属申万一级行业的阶段收益，再与中证 500 做对比，并在全部申万一级行业里按相对强弱排序。默认只保留前 30% 的行业，落在后面的股票会被前置过滤拦截。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">市场环境</el-tag>
                    <p>当前默认检查中证 500 和创业板指：至少有 1 个指数同时满足“收盘价在 20 日 EMA 之上、20 日 EMA 在 60 日 EMA 之上、近 20 日收益为正”，才认为市场环境基本达标。若两个代表性指数都偏弱，系统会减少在弱市中硬做趋势启动的情况。</p>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>四维复核</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag type="success" effect="plain">趋势结构</el-tag>
                    <p>看中短期趋势是否顺畅，均线、价格重心和节奏是否支持“趋势启动”而不是脉冲反弹。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag type="warning" effect="plain">价格位置</el-tag>
                    <p>看当前价格是不是已经太高、离支撑太远，避免在位置不划算时给出过高评价。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag type="danger" effect="plain">量价行为</el-tag>
                    <p>看上涨是否有量能配合、放量是否健康、是否存在明显派发或冲高回落等不良行为。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag type="info" effect="plain">历史异动</el-tag>
                    <p>看过去是否有异常拉升、巨震、长上影或剧烈回撤等痕迹，避免把高波动风险误判成趋势机会。</p>
                  </div>
                </div>
              </div>

              <div class="panel-section">
                <h3>中盘分析术语</h3>
                <div class="definition-list">
                  <div class="definition-item">
                    <el-tag effect="plain">大盘中盘总览</el-tag>
                    <p>顶部会展示代表性指数在中盘时段的方向、量能与 5 日线状态，例如“放量下跌”“缩量上涨”“站上 5 日线”。它不是结论本身，而是下午是否适合继续冒进的背景。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">11:30价</el-tag>
                    <p>指上午收盘附近的定点价格，用来衡量“上午这半天”的真实强弱。它和当前价一起看，可以区分下午是继续强化，还是上午强、下午转弱。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">相对大盘强弱</el-tag>
                    <p>比较个股当前涨跌与参考指数涨跌的差值。若个股在弱市中仍明显跑赢指数，说明有相对强度；若大盘不差但个股明显跑输，说明承接偏弱。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">上午走势状态</el-tag>
                    <p>用中文概括上午盘面的结构特征，例如“盘中下探后收回”“冲高回落偏重”“向上推进顺畅”。重点是帮助你快速判断下午更像继续做趋势，还是优先做风控。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">持仓建议</el-tag>
                    <p>把原先的内部策略码翻译成中文执行语言，例如“先减仓”“退出观望”“继续持有，暂不急于加仓”。它强调的是资金管理动作，而不是系统内部标签。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">执行参考</el-tag>
                    <p>把关键价位、下午动作和原因拼成一句可执行说明，用来看“下午重点盯哪里、为什么这样做”。它相当于中盘时段的简版交易备忘录。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">关键价位</el-tag>
                    <p>中盘会把“上午低点、上午高点、收复线、支撑位、压力位”等翻译后展示。上午低点常用来做防守参考，收复线常用来判断下午是否重新转强。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">热度 / 换手率 / 量比</el-tag>
                    <p>热度用于看该股在活跃资金里的相对排名；换手率看筹码交换是否充分；量比看今天量能相对常态是否放大。三者合起来，用于判断下午是继续聚焦，还是容易冲高回落。</p>
                  </div>
                  <div class="definition-item">
                    <el-tag effect="plain">基金经理视角补充</el-tag>
                    <p>站在私募资金管理的角度，综合昨日结论、今日中盘强弱和大盘环境，强调的是仓位节奏、回撤控制和兑现优先级，而不是只看单一技术信号。</p>
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="选股流程" name="flow">
              <div class="flow-grid">
                <div class="flow-item">
                  <div class="flow-step">01</div>
                  <div>
                    <h3>数据准备</h3>
                    <p>以最新可用交易日收盘后的本地行情数据为基准。</p>
                  </div>
                </div>

                <div class="flow-item">
                  <div class="flow-step">02</div>
                  <div>
                    <h3>流动性入池</h3>
                    <p>按 43 日滚动成交额排序，取前 2000 只形成流动性池。</p>
                  </div>
                </div>

                <div class="flow-item">
                  <div class="flow-step">03</div>
                  <div>
                    <h3>B1 候选筛选</h3>
                    <p>检查 KDJ 低位、知行线结构、周线多头、最大量日非阴线，全部通过才入候选。</p>
                  </div>
                </div>

                <div class="flow-item">
                  <div class="flow-step">04</div>
                  <div>
                    <h3>前置过滤</h3>
                    <p>进一步过滤 ST、次新、解禁、行业强度和市场环境不匹配（例如板块强度不足、指数环境偏弱、风格不共振）的股票。</p>
                  </div>
                </div>

                <div class="flow-item">
                  <div class="flow-step">05</div>
                  <div>
                    <h3>四维复核评分</h3>
                    <p>从趋势结构、价格位置、量价行为、历史异动四个维度评估趋势健康度。</p>
                  </div>
                </div>

                <div class="flow-item">
                  <div class="flow-step">06</div>
                  <div>
                    <h3>先定信号类型，再定结论</h3>
                    <p>系统先判断“信号类型”，再结合总分和关键子项给出 PASS / WATCH / FAIL。</p>
                  </div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const activeTab = ref('usage')
</script>

<style scoped lang="scss">
.system-info-page {
  display: flex;
  flex-direction: column;
  gap: 20px;

  .page-grid {
    display: grid;
    grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
    gap: 24px;
    align-items: start;
  }

  .summary-column,
  .detail-column {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-weight: 600;
  }

  .hero-card,
  .overview-card,
  .tabs-card {
    border-radius: 12px;
  }

  .hero-card,
  .tabs-card,
  .overview-card,
  .risk-alert {
    width: 100%;
    box-sizing: border-box;
  }

  .hero-content {
    h2 {
      margin: 0 0 12px 0;
      font-size: 24px;
      line-height: 1.4;
      color: var(--color-text-primary);
    }

    p {
      margin: 0;
      color: var(--color-text-secondary);
      line-height: 1.8;
    }

    .hero-highlight {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(0, 180, 216, 0.14), rgba(34, 197, 94, 0.14));
      color: #0f766e;
      font-weight: 700;
    }
  }

  .overview-grid {
    display: grid;
    gap: 16px;
  }

  .overview-card {
    .overview-label {
      font-size: 13px;
      color: var(--color-text-secondary);
      margin-bottom: 8px;
    }

    .overview-value {
      font-size: 28px;
      font-weight: 700;
      color: var(--color-primary);
      margin-bottom: 10px;
    }

    p {
      margin: 0;
      color: var(--color-text-secondary);
      line-height: 1.7;
    }

    &.coming-soon {
      opacity: 0.6;
      position: relative;
      cursor: not-allowed;
      user-select: none;

      .coming-soon-content {
        pointer-events: none;
      }

      .overview-label,
      .overview-value {
        color: #9ca3af;
      }

      p {
        color: #9ca3af;
      }

      // Enable tooltips only
      :deep(.el-tooltip__trigger) {
        pointer-events: auto !important;
        cursor: help;
      }
    }
  }

  .tabs-card {
    min-height: 100%;

    :deep(.el-card__body) {
      padding-top: 18px;
    }
  }

  .info-tabs {
    :deep(.el-tabs__header) {
      margin-bottom: 18px;
      padding-bottom: 4px;
      border-bottom: 1px solid #eef2f7;
    }
  }

  .panel-section + .panel-section {
    margin-top: 24px;
  }

  .panel-section h3 {
    margin: 0 0 14px 0;
    font-size: 16px;
    color: var(--color-text-primary);
  }

  .usage-list,
  .definition-list,
  .verdict-list,
  .flow-grid {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .usage-item,
  .definition-item,
  .verdict-item,
  .flow-item,
  .logic-card {
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--color-bg-light);
  }

  .usage-item,
  .flow-item {
    display: flex;
    gap: 14px;
    align-items: flex-start;
  }

  .usage-step,
  .flow-step {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    flex-shrink: 0;
    background: rgba(0, 180, 216, 0.12);
    color: var(--color-primary);
  }

  .usage-item strong,
  .logic-card strong,
  .verdict-title {
    font-size: 15px;
    color: var(--color-text-primary);
  }

  .usage-item p,
  .definition-item p,
  .verdict-item p,
  .flow-item p,
  .logic-card p {
    margin: 8px 0 0 0;
    color: var(--color-text-secondary);
    line-height: 1.7;
  }

  .flow-item h3 {
    margin: 0 0 6px 0;
    font-size: 16px;
    color: var(--color-text-primary);
  }

  .logic-card + .logic-card {
    margin-top: 12px;
  }

  .verdict-item {
    border-left: 4px solid transparent;

    &.pass {
      border-left-color: var(--color-success);
      .verdict-title {
        color: var(--color-success);
      }
    }

    &.watch {
      border-left-color: var(--color-warning);
      .verdict-title {
        color: var(--color-warning);
      }
    }

    &.fail {
      border-left-color: var(--color-danger);
      .verdict-title {
        color: var(--color-danger);
      }
    }
  }

  .risk-alert {
    width: 100%;
    box-sizing: border-box;

    :deep(p) {
      margin: 6px 0;
      line-height: 1.7;
    }
  }
}

@media (max-width: 767px) {
  .system-info-page {
    gap: 16px;

    .page-grid {
      grid-template-columns: 1fr;
      gap: 14px;
    }

    .summary-column,
    .detail-column {
      gap: 14px;
    }

    .section-header {
      align-items: flex-start;
      flex-direction: column;
    }

    .hero-content {
      h2 {
        font-size: 20px;
      }
    }

    .tabs-card {
      :deep(.el-card__body) {
        padding: 14px;
      }
    }

    .info-tabs {
      :deep(.el-tabs__header) {
        margin-bottom: 14px;
      }

      :deep(.el-tabs__nav-wrap) {
        padding-bottom: 4px;
      }

      :deep(.el-tabs__item) {
        padding: 0 12px;
        font-size: 13px;
      }
    }

    .usage-item,
    .definition-item,
    .verdict-item,
    .flow-item,
    .logic-card {
      padding: 12px 14px;
    }

    .usage-item,
    .flow-item {
      gap: 12px;
    }

    .usage-step,
    .flow-step {
      width: 32px;
      height: 32px;
      font-size: 13px;
    }

    .risk-alert {
      :deep(.el-alert__content) {
        font-size: 13px;
      }
    }
  }
}

@media (max-width: 960px) {
  .system-info-page {
    .page-grid {
      grid-template-columns: 1fr;
      gap: 16px;
    }

    .summary-column,
    .detail-column {
      gap: 16px;
    }
  }
}
</style>
