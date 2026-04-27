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
            <h2>先筛候选，再做复核，再给结论。</h2>
            <p>系统默认围绕“低位启动 + 趋势健康度”工作，不直接做全市场盲打分。</p>
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
            <div class="overview-label">最终结论</div>
            <div class="overview-value">3 档</div>
            <p>输出 PASS / WATCH / FAIL，不只看总分。</p>
          </el-card>

          <el-card class="overview-card coming-soon">
            <template #default>
              <div class="coming-soon-content">
                <el-tooltip content="待开发" placement="top">
                  <div class="overview-label">LLM 评分</div>
                </el-tooltip>
                <div class="overview-value">
                  <el-tooltip content="待开发" placement="top">
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
                    <p>进一步过滤 ST、次新、解禁、行业强度和市场环境不匹配的股票。</p>
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
                    <h3>先定信号，再定结论</h3>
                    <p>系统先判断 signal_type，再结合总分和关键子项给出 PASS / WATCH / FAIL。</p>
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
