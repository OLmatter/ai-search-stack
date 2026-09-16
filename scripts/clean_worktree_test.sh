#!/usr/bin/env bash
# clean-worktree 收工检查（v3.23 固化）：在 HEAD 的全新 checkout 里跑全量测试。
#
# 为什么需要（盲区实证 v3.22）：
#   机器本地的 gitignore 产物（state/、__pycache__、.env…）会造成
#   「本机绿 ≠ fresh 绿」假象——v3.18 批次的 test_v3180 真仓 shift_log
#   钉在 fresh checkout 上必炸，被本地 state/shift_log.md 在场掩盖了
#   整整一轮（"352 全绿"是假象）。
#
# 为什么是 git worktree 而不是 git stash：
#   git stash（含 -u）不触碰 gitignore 文件——state/、__pycache__ 原地
#   保留，恰恰漏掉本检查要暴露的那类产物；-a（含 ignored）还会把
#   zhihu_cookies.json 等运行态文件卷进 stash，pop 冲突风险真实存在。
#   git worktree add 产出只含被跟踪文件的真实 fresh checkout，且完全不
#   触碰当前工作区（零 stash-pop 风险）。
#
# 用法：
#   bash scripts/clean_worktree_test.sh [repo_dir] [pytest 参数...]
#   repo_dir 缺省 = 本脚本所在仓库根；pytest 参数原样转发（默认跑 tests/ -q）。
#   测的是 HEAD（已提交状态）——push 的是提交，所以先提交再跑本检查。
# 退出码：pytest 的退出码；2 = 用法/仓库错误。

set -euo pipefail

REPO="${1:-}"
if [ -n "$REPO" ]; then
    shift
else
    REPO="$(cd "$(dirname "$0")/.." && pwd)"
fi

if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[clean-worktree] 错误：$REPO 不是 git 仓库" >&2
    exit 2
fi

if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
    echo "[clean-worktree] 注意：工作区有未提交改动——本检查测的是 HEAD，" \
         "push 前先提交再跑" >&2
fi

TMPROOT="$(mktemp -d)"
WT="$TMPROOT/wt"
cleanup() {
    git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || true
    rm -rf "$TMPROOT" 2>/dev/null || true
}
trap cleanup EXIT

git -C "$REPO" worktree add --detach "$WT" HEAD >/dev/null
HEAD_SHORT="$(git -C "$REPO" rev-parse --short HEAD)"
echo "[clean-worktree] fresh checkout: $WT (HEAD=$HEAD_SHORT)"

cd "$WT"
rc=0
python -m pytest tests/ -q "$@" || rc=$?
echo "[clean-worktree] exit=$rc (HEAD=$HEAD_SHORT)"
exit "$rc"
