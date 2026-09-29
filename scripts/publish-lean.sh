#!/usr/bin/env zsh
# 将 gpui(完整合并历史,含上游历史)压缩发布为 lean 快照链。
#
# 背景: gpui 分支与上游 zed 共享全部历史(4 万+提交, .git ~800MB)。
# 使用者克隆 gpui 会被迫下载完整 zed 历史。lean 分支是一条孤儿根起点的
# 线性快照链: 每个快照是当次 gpui 树的单父提交, 不含上游历史对象。
# 将 lean 设为仓库默认分支后, 使用者克隆/拉取默认只下载 lean 内容;
# git 对未变化的 blob/tree 去重, 后续增量拉取只传输有变化的部分。
#
# 自包含: lean 的树不是 gpui 的原始树, 而是经过 scripts/expand-workspace.py
# 展开工作区继承(dep.workspace = true 等)后的树。使用者把本仓库作为
# submodule 引入并通过 path 依赖引用 gpui 等 crate 时, Cargo 会把继承项
# 向上解析到"使用者的"工作区根, 未展开的继承会导致构建失败。展开后每个
# crate 自带完整依赖定义, 使用者无需重建本仓库的工作区表。
# 所有展开复杂度都封闭在本仓库内部, 使用者只消费展开后的结果。
#
# 用法:
#   scripts/publish-lean.sh            # 从 gpui 生成下一个快照到 lean
#   scripts/publish-lean.sh --push     # 生成后推送到 origin/lean
#   scripts/publish-lean.sh --dry-run  # 只构建快照树并报告, 不移动 lean
#   scripts/publish-lean.sh <branch>   # 从其他分支生成, 默认 gpui
#
# 工作流: 本地 gpui 上正常 merge upstream/main 解决冲突(见
# docs/dev/branch-sync.md), 完成后运行本脚本发布。

set -euo pipefail

PUSH=false
DRY_RUN=false
SRC="gpui"
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=true ;;
    --dry-run) DRY_RUN=true ;;
    -*) echo "Unknown option: $arg" >&2; exit 2 ;;
    *) SRC="$arg" ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

DST="lean"
SRC_SUBJECT="$(git log -1 --format=%s "$SRC")"
PARENT="$(git rev-parse -q --verify "refs/heads/$DST" 2>/dev/null || true)"

SCRIPT_DIR="$REPO_ROOT/scripts"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 1. 把 SRC 的树导出到 WORK/tree(git archive 不含 .git, 与快照语义一致)。
mkdir -p "$WORK/tree"
git archive "$SRC" | tar -x -C "$WORK/tree"

# 2. 展开工作区继承, 结果写入 WORK/expanded。
python3 "$SCRIPT_DIR/expand-workspace.py" "$WORK/tree" "$WORK/expanded"

# 3. 用临时索引把展开后的目录写成树对象。
#    在 expanded 目录内以相对路径建索引, 保证写入的路径干净(不带临时前缀);
#    GIT_DIR 必须显式指定, 因为 cd 到临时目录后 git 找不到仓库。
(
  cd "$WORK/expanded"
  export GIT_INDEX_FILE="$WORK/index" GIT_DIR="$REPO_ROOT/.git" GIT_WORK_TREE="$WORK/expanded"
  git read-tree --empty
  git add -A -- .
  git write-tree > "$WORK/tree-id"
)
TREE="$(cat "$WORK/tree-id")"

if $DRY_RUN; then
  echo "dry run: snapshot tree $TREE"
  echo "  files: $(git ls-tree -r "$TREE" | wc -l | tr -d ' ')"
  git ls-tree "$TREE"
  if [[ -n "$PARENT" ]]; then
    echo "  current $DST tree: $(git rev-parse "${DST}^{tree}")"
  fi
  exit 0
fi

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
the trimmed content. Workspace inheritance is expanded so the tree is
self-contained for downstream path dependencies. See
docs/dev/branch-sync.md.")"
fi

git update-ref "refs/heads/$DST" "$NEW"
echo "lean -> $(git rev-parse --short "$NEW")  $SRC_SUBJECT"

if $PUSH; then
  git push origin "$DST"
fi
