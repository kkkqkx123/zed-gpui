#!/usr/bin/env zsh
# 将 gpui(完整合并历史,含上游历史)压缩发布为 lean 快照链。
#
# 背景: gpui 分支与上游 zed 共享全部历史(4 万+提交, .git ~800MB)。
# 使用者克隆 gpui 会被迫下载完整 zed 历史。lean 分支是一条孤儿根起点的
# 线性快照链: 每个快照是当次 gpui 树的单父提交, 不含上游历史对象。
# 将 lean 设为仓库默认分支后, 使用者克隆/拉取默认只下载 lean 内容;
# git 对未变化的 blob/tree 去重, 后续增量拉取只传输有变化的部分。
#
# 用法:
#   scripts/publish-lean.sh          # 从 gpui 生成下一个快照到 lean
#   scripts/publish-lean.sh --push   # 生成后推送到 origin/lean
#   scripts/publish-lean.sh <branch> # 从其他分支生成, 默认 gpui
#
# 工作流: 本地 gpui 上正常 merge upstream/main 解决冲突(见
# docs/dev/branch-sync.md), 完成后运行本脚本发布。

set -euo pipefail

PUSH=false
SRC="gpui"
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=true ;;
    *) SRC="$arg" ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

DST="lean"
TREE="$(git rev-parse "${SRC}^{tree}")"
SRC_SUBJECT="$(git log -1 --format=%s "$SRC")"
PARENT="$(git rev-parse -q --verify "refs/heads/$DST" 2>/dev/null || true)"

if [[ -n "$PARENT" ]]; then
  if [[ "$TREE" == "$(git rev-parse "${DST}^{tree}")" ]]; then
    echo "lean is already up to date with $SRC (tree unchanged)."
    exit 0
  fi
  NEW="$(git commit-tree "$TREE" -p "$PARENT" -m "$SRC_SUBJECT")"
else
  NEW="$(git commit-tree "$TREE" -m "Snapshot of ${SRC}: zed trimmed to GPUI

History trimmed: this branch starts from a tree snapshot of the gpui
branch and carries no upstream zed history, so cloning downloads only
the trimmed content. See docs/dev/branch-sync.md.")"
fi

git update-ref "refs/heads/$DST" "$NEW"
echo "lean -> $(git rev-parse --short "$NEW")  $SRC_SUBJECT"

if $PUSH; then
  git push origin "$DST"
fi
