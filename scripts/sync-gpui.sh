#!/usr/bin/env zsh
# 同步 gpui 分支(裁剪分支)到上游 zed-industries/zed 的 main。
#
# gpui 分支基于 main 之上只有一个裁剪提交, 与上游的冲突几乎都是
# modify/delete 类型(本分支删除的文件被上游修改)。本脚本默认
# 对这类冲突一律"保留删除"(-X d), 以维持裁剪决策。
#
# 用法:
#   scripts/sync-gpui.sh            # 冲突按默认策略解决(保留删除)
#   scripts/sync-gpui.sh --manual   # 遇到冲突停下手动处理
#   scripts/sync-gpui.sh --push     # 同步后推送到 origin/gpui
#
# 可选参数可与 --push 组合, 如: scripts/sync-gpui.sh --manual --push

set -euo pipefail

PUSH=false
MANUAL=false
for arg in "$@"; do
  case "$arg" in
    --push)  PUSH=true ;;
    --manual) MANUAL=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# 如需代理, 请在运行前手动设置, 如:
#   export https_proxy=http://localhost:7890 http_proxy=http://localhost:7890
UPSTREAM_URL="https://github.com/zed-industries/zed.git"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "$UPSTREAM_URL"
  echo "Added upstream remote: $UPSTREAM_URL"
fi

ORIG_BRANCH="$(git branch --show-current)"
git checkout gpui
git fetch upstream main

BEHIND="$(git rev-list --count gpui..upstream/main)"
if [[ "$BEHIND" -eq 0 ]]; then
  echo "gpui is already up to date with upstream/main."
else
  echo "gpui is $BEHIND commit(s) behind upstream/main, merging..."
  if $MANUAL; then
    git merge upstream/main --no-edit
  else
    # -X d: modify/delete 冲突时保留我方删除
    git merge upstream/main --no-edit -X d
  fi
  $PUSH && git push origin gpui
fi

if [[ "$ORIG_BRANCH" != "gpui" ]]; then
  git checkout "$ORIG_BRANCH"
fi
echo "Done."
