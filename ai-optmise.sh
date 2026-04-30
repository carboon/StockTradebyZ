#!/usr/bin/env bash

# === 颜色高亮定义 ===
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

OS_TYPE=$(uname -s)

echo -e "${BLUE}===================================================${NC}"
echo -e "${BLUE}>>> 🚀 正在初始化跨平台 AI 开发环境 (macOS/Ubuntu) <<<${NC}"
echo -e "${BLUE}===================================================${NC}\n"

echo -e "🖥️  检测到操作系统: ${YELLOW}${OS_TYPE}${NC}\n"

# 1. 跨平台依赖安装
echo -e "${GREEN}[1/4] 检查并安装底层沙盒与 RTK 组件...${NC}"

if [ "$OS_TYPE" = "Darwin" ]; then
    # macOS 依赖分支
    if ! command -v brew > /dev/null 2>&1; then
        echo -e "${RED}❌ 未检测到 Homebrew。请先安装后再运行此脚本。${NC}"; exit 1
    fi
    if ! command -v ai-jail > /dev/null 2>&1; then
        brew tap akitaonrails/tap && brew install ai-jail
    else
        echo -e "  ✅ [macOS] ai-jail 已安装"
    fi
    if ! command -v rtk > /dev/null 2>&1; then
        brew install rtk && rtk init --global > /dev/null 2>&1
    else
        echo -e "  ✅ [macOS] rtk 已安装"
    fi

elif [ "$OS_TYPE" = "Linux" ]; then
    # Ubuntu/Linux 依赖分支
    if ! command -v bwrap > /dev/null 2>&1; then
        echo -e "  📥 [Linux] 正在通过 apt 安装 bubblewrap (bwrap)..."
        sudo apt-get update && sudo apt-get install -y bubblewrap
    else
        echo -e "  ✅ [Linux] bubblewrap 已安装"
    fi
    
    if ! command -v rtk > /dev/null 2>&1; then
        if command -v brew > /dev/null 2>&1; then
            echo -e "  📥 [Linux] 检测到 Linuxbrew，正在安装 rtk..."
            brew install rtk && rtk init --global > /dev/null 2>&1
        elif command -v cargo > /dev/null 2>&1; then
            echo -e "  📥 [Linux] 正在使用 Cargo 安装 rtk (首次编译需要几十秒)..."
            cargo install rtk && rtk init --global > /dev/null 2>&1
        else
            echo -e "${YELLOW}⚠️ 警告：Linux 下未检测到 Homebrew 或 Cargo。${NC}"
            echo -e "${YELLOW}👉 请手动执行命令安装 Rust 工具链：curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh${NC}"
            echo -e "${YELLOW}安装完成后，请重新运行此脚本。${NC}"
            exit 1
        fi
    else
        echo -e "  ✅ [Linux] rtk 已安装"
    fi
else
    echo -e "${RED}❌ 不支持的操作系统: $OS_TYPE${NC}"; exit 1
fi

# 2. 构建跨平台模块化提示词
echo -e "\n${GREEN}[2/4] 初始化模块化系统提示词 (~/.claude/)...${NC}"
mkdir -p ~/.claude

# 2.1 RTK.md
if [ ! -f ~/.claude/RTK.md ]; then
cat > ~/.claude/RTK.md << 'EOF'
# RTK - Rust Token Killer

**Usage**: Token-optimized CLI proxy (60-90% savings on dev operations)

## Meta Commands (always use rtk directly)
```bash
rtk gain              # Show token savings analytics
rtk proxy <cmd>       # Execute raw command without filtering
```
## Hook-Based Usage
All other commands are automatically rewritten by the Claude Code hook.
EOF
    echo -e "  ✅ RTK.md 模块已创建"
else
    echo -e "  ⏭️ ${YELLOW}RTK.md 已存在，跳过覆盖${NC}"
fi

# 2.2 跨平台 SANDBOX.md
if [ ! -f ~/.claude/SANDBOX.md ]; then
cat > ~/.claude/SANDBOX.md << 'EOF'
# 🛡️ OS Sandbox Security (ai-jail / bubblewrap)

**Status**: Active strict kernel-level isolation.

## Constraints & Permissions
- **Scope**: You ONLY have read/write access to the current project directory, `/tmp`, and specific cache dirs.
- **System Isolation**: Do NOT attempt to read/modify global user configs (e.g., `~/.ssh`, `~/.aws`). 
- **Behavior**: The kernel will instantly block unauthorized access with a `Permission denied` error. Do not attempt to bypass this. Just inform me.

## 🔍 Pre-flight Security Check
Attempt to read `ls ~/.ssh`. 
- If SUCCEED: Warn me: "⚠️ **警告：未开启沙盒隔离，存在越权风险！**"
- If Permission Denied: **Remain silent** and proceed.
EOF
    echo -e "  ✅ 跨平台 SANDBOX.md 模块已创建"
else
    echo -e "  ⏭️ ${YELLOW}SANDBOX.md 已存在，跳过覆盖${NC}"
fi

# 2.3 智能增量更新 CLAUDE.md
CLAUDE_FILE="$HOME/.claude/CLAUDE.md"
if [ ! -f "$CLAUDE_FILE" ]; then touch "$CLAUDE_FILE"; fi

if ! grep -q "@RTK\.md" "$CLAUDE_FILE"; then printf "@RTK.md\n" | cat - "$CLAUDE_FILE" > temp && mv temp "$CLAUDE_FILE"; fi
if ! grep -q "@SANDBOX\.md" "$CLAUDE_FILE"; then printf "@SANDBOX.md\n" | cat - "$CLAUDE_FILE" > temp && mv temp "$CLAUDE_FILE"; fi
if ! grep -q "Cross-Module Integration Rule" "$CLAUDE_FILE"; then
    cat >> "$CLAUDE_FILE" << 'EOF'

# 🚨 Cross-Module Integration Rule
If you suspect you are missing critical logs due to RTK compression (e.g., debugging deep Java/Spring issues), you **MUST** use:
- **Correct**: `rtk proxy mvn clean test`
EOF
    echo -e "  ➕ 已追加模块联动规则"
fi

# 3. Git 忽略
echo -e "\n${GREEN}[3/4] 配置全局 Git 忽略规则...${NC}"
touch ~/.gitignore_global
for item in "CLAUDE.md" "RTK.md" "SANDBOX.md" ".ai-jail"; do
    if ! grep -q "^${item}$" ~/.gitignore_global; then echo "${item}" >> ~/.gitignore_global; fi
done
git config --global core.excludesfile ~/.gitignore_global
echo -e "  ✅ Git 忽略规则已更新"

# 4. 注入跨平台双分支 Shell 包装器
echo -e "\n${GREEN}[4/4] 注入动态跨平台启动包装器...${NC}"
SHELL_RC="$HOME/.bashrc"
if [ -n "$ZSH_VERSION" ] || [ "$(basename "$SHELL")" = "zsh" ]; then SHELL_RC="$HOME/.zshrc"; fi

WRAPPER_FUNC=$(cat << 'EOF'

# --- 🌐 跨平台 AI Dev Wrapper ---
claude_wrapper() {
    # 自动链接模块化提示词
    for f in CLAUDE.md RTK.md SANDBOX.md; do
        if [ ! -f "$f" ] && [ -f "$HOME/.claude/$f" ]; then
            ln -s "$HOME/.claude/$f" "$f"
        fi
    done
    
    RUNTIME_OS=$(uname -s)
    
    if [ "$RUNTIME_OS" = "Darwin" ]; then
        # === macOS 分支 (ai-jail) ===
        if [ ! -f ".ai-jail" ]; then
            ai-jail --clean --init > /dev/null 2>&1
            cat >> .ai-jail << EOT
rw_maps = [ "$HOME/.local/share/rtk" ]
ro_maps = [ "$HOME/.config/rtk", "/opt/homebrew/bin", "/opt/homebrew/Cellar", "/opt/homebrew/opt" ]
EOT
        fi
        PATH="/opt/homebrew/bin:$PATH" ai-jail claude --dangerously-skip-permissions "$@"
        
    elif [ "$RUNTIME_OS" = "Linux" ]; then
        # === Ubuntu/Linux 分支 (bwrap) ===
        # 挂载必需的目录，注入 Cargo 环境路径，执行安全沙盒拦截
        PATH="$HOME/.cargo/bin:/home/linuxbrew/.linuxbrew/bin:$PATH" bwrap \
            --ro-bind / / \
            --dev-bind /dev /dev \
            --proc /proc \
            --bind /tmp /tmp \
            --bind "$PWD" "$PWD" \
            --bind-try /run /run \
            --bind-try "$HOME/.local/share/rtk" "$HOME/.local/share/rtk" \
            --bind-try "$HOME/.config/rtk" "$HOME/.config/rtk" \
            --bind-try "$HOME/.npm" "$HOME/.npm" \
            --bind-try "$HOME/.cache" "$HOME/.cache" \
            claude --dangerously-skip-permissions "$@"
    else
        echo "不支持的系统平台，回退到裸机执行..."
        claude --dangerously-skip-permissions "$@"
    fi
}
alias claude='claude_wrapper'
# ----------------------------------
EOF
)

if ! grep -q "claude_wrapper()" "$SHELL_RC"; then
    echo "$WRAPPER_FUNC" >> "$SHELL_RC"
    echo -e "  ✅ 已将跨平台包装器写入 $SHELL_RC"
else
    echo -e "  ⏭️ ${YELLOW}检测到包装器已存在，跳过写入${NC}"
fi

echo -e "\n${BLUE}===================================================${NC}"
echo -e "${GREEN}🎉 跨平台底层架构部署完毕！${NC}"
echo -e "${BLUE}===================================================${NC}"
echo -e "⚠️  ${RED}请手动执行以下命令生效：${NC}\n"
echo -e "   ${YELLOW}source $SHELL_RC${NC}\n"
