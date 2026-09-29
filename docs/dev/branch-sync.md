# 分支同步指南(main / gpui ⇄ 上游 zed)

本仓库是 `zed-industries/zed` 的裁剪 fork,保留两条长期分支:

| 分支 | 内容 | 远程 |
|---|---|---|
| `main` | 与上游 `zed-industries/zed` main 保持一致,不含本地提交 | `origin/main` |
| `gpui` | 在 main 之上叠加裁剪提交(裁掉 editor/agent 等非 GPUI 相关代码),含完整上游合并历史 | `origin/gpui` |
| `lean` | gpui 的**展开后**树快照链:孤儿根起点的线性单父提交,克隆使用者应使用的分支 | `origin/lean` |

远程配置:

- `origin` — `https://github.com/kkkqkx123/zed-gpui`(fork)
- `upstream` — `https://github.com/zed-industries/zed`(上游,首次运行同步脚本会自动添加)

## 历史模型:为什么要 lean 分支

gpui 与上游共享全部历史(4 万+ 提交,`.git` ~800MB)。若使用者克隆 gpui,会被迫下载完整 zed 历史,网络开销巨大。

因此额外维护 **lean 快照链**:

- `main` 与 `gpui` 照常推送,用于维护者与上游做正常的三方合并(保留合并历史,冲突解决能力强);
- 每次同步完成后,运行 `scripts/publish-lean.sh`,用 `git commit-tree` 把 gpui 当前的**树**生成为 lean 上的一个单父快照提交;
- lean 的根提交是孤儿提交,不引用任何上游历史对象;git 对未变化的 blob/tree 自动去重,克隆与后续增量拉取只传输裁剪后且实际变化的内容;
- 将 lean 设为 GitHub 默认分支后,使用者克隆/拉取默认只下载 lean,不接触上游完整历史。

### 为什么 lean 还要展开工作区继承

使用者把本仓库作为 **submodule** 引入,再通过 `path` 依赖引用 `crates/gpui` 等 crate:

```toml
[dependencies]
gpui = { path = "crates/vendor/zed-gpui/crates/gpui" }
```

Cargo 解析工作区继承(`dep.workspace = true`、`edition.workspace = true`、`lints.workspace = true`)时,会向上找到**使用者构建的工作区根**,并越过 path 依赖所在的仓库边界继续上溯。也就是说,只要 `crates/gpui/Cargo.toml` 里还有一个 `workspace = true`,`cargo` 就会去使用者的工作区里找 `[workspace.dependencies]`——使用者被迫重建本仓库的工作区表才能编译。仓库内再嵌套一个 `[workspace]` 也**不能**阻止这种上溯。

因此 `publish-lean.sh` 在生成快照时调用 `scripts/expand-workspace.py`,把每个 crate 的继承项改写成展开形式:

- `edition.workspace = true` → `edition = "2024"`
- `serde = { workspace = true, optional = true }` → 带回版本/path/features 的完整定义
- `[lints] workspace = true` → 展开成 `[lints.rust]`、`[lints.clippy]` 等具体表
- 工作区里的 `path` 是相对**仓库根**的,展开时按 crate 实际深度重算(如 `path = "../bench_metrics"`)

展开后每个 crate 自带完整依赖定义,使用者直接用 path 依赖即可编译,无需任何额外配合。原树文本只存在于 `gpui` 分支,所以与上游的合并冲突面保持在裁剪提交的规模,只有生成物 `lean` 带展开。

需要看展开结果而不动分支时:

```bash
scripts/publish-lean.sh --dry-run   # 只构建快照树并打印清单,不移动 lean
```

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

### `scripts/publish-lean.sh`

```bash
scripts/publish-lean.sh            # 把 gpui 当前树展开并发布为 lean 的下一个快照
scripts/publish-lean.sh --push     # 发布后推送到 origin/lean
scripts/publish-lean.sh --dry-run  # 只构建并打印快照树,不移动 lean
```

在 `sync-gpui.sh`(或本地开发提交)完成后运行。脚本流程:导出 `gpui` 树 → 运行
`scripts/expand-workspace.py` 展开工作区继承 → 用临时索引把展开结果写成新树 →
`git commit-tree` 生成单父快照。lean 无变化时脚本是幂等的(树哈希一致则直接跳过)。

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
4. 验证裁剪后仓库仍可构建(至少 `cargo check -p gpui`;未展开的 `gpui` 分支在本仓库内构建正常,因为工作区根就在本仓库)
5. 发布快照并推送:`scripts/publish-lean.sh --push`(发布前可先 `--dry-run` 看清单)

## 常见问题

**Q: 为什么不用 rebase 让 gpui 始终只差一个提交?**
rebase 裁剪提交会重放对上千个文件的删除操作,与上游冲突概率高、且每次 rebase 后 fork 需强推。merge 保留历史、冲突面小,适合长期维护。

**Q: 使用者的仓库里也要放 `[workspace.dependencies]` 吗?**
不需要。lean 里的每个 crate 都是自包含的,使用者只写 path 依赖即可。如果使用者遇到 `error inheriting ... from workspace root manifest`,说明引用的是未展开的 `gpui` 分支而非 `lean`,或该 crate 的继承项未被展开(检查 `expand-workspace.py` 的 `unresolved` 输出)。

**Q: 新增 crate 时要改脚本吗?**
不用。`expand-workspace.py` 遍历 `crates/` 与 `tooling/` 下所有带 `[package]` 的 manifest,自动发现新 crate。但若引入**新的继承形式**(如新的 `xxx.workspace = true` 字段),需在脚本的 `expand_*` 函数中补充处理;脚本会在遇到未解析的依赖名时报错退出,不会静默产出错误快照。

**Q: 网络不通怎么办?**
脚本会因 fetch 失败而中止(set -euo pipefail)。如需代理,运行前手动 `export https_proxy=... http_proxy=...`。
