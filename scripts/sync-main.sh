#!/usr/bin/env bash
# 同步 main 分支到上游 zed-industries/zed 的最新提交。
# 用法: scripts/sync-main.sh [--push]
#
# 策略: main 跟踪上游 main, 始终使用 fast-forward, 不产生本地提交。
set -euo pipefail

PUSH=false
[[ "${1:-}" == "--push" ]] && PUSH=true

# 如需代理, 请在运行前手动设置, 如:
#   export https_proxy=http://localhost:7890 http_proxy=http://localhost:7890
UPSTREAM_URL="https://github.com/zed-industries/zed.git"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# 幂等配置 upstream 远程
if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "$UPSTREAM_URL"
  echo "Added upstream remote: $UPSTREAM_URL"
fi

CURRENT_BRANCH="$(git branch --show-current)"

# 保存当前分支, 切到 main 执行同步
git checkout main
git fetch upstream main
BEHIND="$(git rev-list --count main..upstream/main)"
if [[ "$BEHIND" -eq 0 ]]; then
  echo "main is already up to date with upstream/main."
else
  echo "main is $BEHIND commit(s) behind upstream/main, fast-forwarding..."
  git merge --ff-only upstream/main
  $PUSH && git push origin main
fi

# 回到原分支
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  git checkout "$CURRENT_BRANCH"
fi
echo "Done."
