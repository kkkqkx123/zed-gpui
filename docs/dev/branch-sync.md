# 分支同步指南(main / gpui ⇄ 上游 zed)

本仓库是 `zed-industries/zed` 的裁剪 fork,保留两条长期分支:

| 分支 | 内容 | 远程 |
|---|---|---|
| `main` | 与上游 `zed-industries/zed` main 保持一致,不含本地提交 | `origin` |
| `gpui` | 在 main 之上叠加一个裁剪提交(裁掉 editor/agent 等非 GPUI 相关代码),用于独立使用/优化 GPUI | `origin` |

远程配置:

- `origin` — `https://github.com/kkkqkx123/zed-gpui`(fork)
- `upstream` — `https://github.com/zed-industries/zed`(上游,首次运行同步脚本会自动添加)

网络要求:如需代理,在运行脚本前手动设置环境变量,例如:

```bash
export https_proxy=http://localhost:7890 http_proxy=http://localhost:7890
```

## 同步策略

- **main → 上游**:始终 `git merge --ff-only upstream/main`,main 永远是上游的镜像,不产生本地提交,保证 gpui 的 rebase/merge 基准干净。
- **gpui → 上游**:`git merge upstream/main`。gpui 分支相对 main 只有一个裁剪提交,冲突几乎全部是 **modify/delete** 类型(本分支删除的文件被上游改动)。默认策略是 **保留删除**(`git merge -X d`),即维持裁剪决策,不把上游对已删文件的改动拉回来。

如果某次上游改动确实需要恢复某个被裁剪的文件(例如该文件被 gpui 依赖),先按默认策略完成合并,再单独 `git checkout upstream/main -- <path>` 恢复并提交;不要在合并时逐个裁决,避免遗漏。

## 脚本

### `scripts/sync-main.sh`

```bash
scripts/sync-main.sh           # 同步 main 到上游
scripts/sync-main.sh --push    # 同步后推送 origin/main
```

流程:配置 upstream(幂等)→ checkout main → fetch → `merge --ff-only` → 可选 push → 切回原分支。

### `scripts/sync-gpui.sh`

```bash
scripts/sync-gpui.sh             # 同步 gpui,modify/delete 冲突自动保留删除
scripts/sync-gpui.sh --manual    # 遇到冲突停下手动处理
scripts/sync-gpui.sh --push      # 同步后推送 origin/gpui
```

流程:配置 upstream(幂等)→ checkout gpui → fetch → `merge upstream/main`(默认带 `-X d`)→ 可选 push → 切回原分支。

## 冲突处理

### modify/delete(最常见)

上游修改了 gpui 分支已删除的文件。脚本默认用 `-X d` 保留删除。手动处理时:

```bash
git rm <path>        # 保留删除(维持裁剪)
# 或
git add <path>       # 恢复文件(接受上游版本)
```

### 内容冲突(少见)

只会出现在 gpui 裁剪提交触碰过、且上游也改动的文件中(如 `crates/gpui/` 下的文件)。正常按内容裁决即可。

## 建议的操作顺序

1. 先同步 main:`scripts/sync-main.sh`
2. 再同步 gpui:`scripts/sync-gpui.sh`
3. 冲突解决后,确认合并提交包含预期改动:`git log -1 --stat`
4. 验证裁剪后仓库仍可构建(至少 `cargo check -p gpui`)
5. 推送:`scripts/sync-gpui.sh --push`(或单独 `git push origin gpui`)

## 常见问题

**Q: 为什么不用 rebase 让 gpui 始终只差一个提交?**
rebase 裁剪提交会重放对上千个文件的删除操作,与上游冲突概率高、且每次 rebase 后 fork 需强推。merge 保留历史、冲突面小,适合长期维护。

**Q: 网络不通怎么办?**
脚本会因 fetch 失败而中止(set -euo pipefail)。如需代理,运行前手动 `export https_proxy=... http_proxy=...`。
