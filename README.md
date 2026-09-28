> [!IMPORTANT]
> Remove this line to confirm you've reviewed this PR before submitting.

# zed-gpui (gpui 分支)

本仓库是 [zed-industries/zed](https://github.com/zed-industries/zed) 的裁剪 fork,只保留 GPUI UI 框架及其直接依赖,用于独立开发、优化和基准测试 GPUI。

**使用者请检出 `lean` 分支**(仓库默认分支):它是 gpui 工作内容的树快照链,不含上游 zed 的完整历史,克隆与拉取的开销极小。

维护者使用的分支:

| 分支 | 内容 |
|---|---|
| `main` | 上游 `zed-industries/zed` main 的镜像,无本地提交 |
| `gpui` | 在 main 之上叠加裁剪提交,仅保留 GPUI 相关 crate |
| `lean` | gpui 的树快照链(对外使用),详细模型见 [docs/dev/branch-sync.md](docs/dev/branch-sync.md) |

裁剪后的工作区(见根 `Cargo.toml` 的 `members`):

- **GPUI 核心**:`crates/gpui`、`gpui_macros`、`gpui_platform` 及各平台后端(`gpui_linux`、`gpui_macos`、`gpui_windows`、`gpui_apple`、`gpui_web`、`gpui_wgpu`、`gpui_tokio`、`gpui_shared_string`)
- **基础库**:`collections`、`sum_tree`、`util`、`util_macros`、`refineable`、`path`、`scheduler`、`zlog`、`ztracing`(+ macro)、`bench_metrics`
- **网络与设置**:`http_client`、`http_client_tls`、`reqwest_client`、`settings`、`settings_content`、`settings_ui`
- **保留的上层示例**:`theme`、`ui`、`sidebar`、`language`、`editor`、`agent_ui` 等(作为 GPUI 的真实使用方,用于回归验证)
- **工具**:`tooling/perf`(`util_macros` 依赖)

`default-members = ["crates/gpui"]`,直接 `cargo build` / `cargo check` 只构建 gpui。

## 常用命令

```bash
cargo check -p gpui      # 检查 gpui 本体
cargo test -p gpui       # 运行 gpui 测试
./script/clippy          # clippy(上游脚本,如已裁剪则用 cargo clippy)
```

## 与上游同步

如需代理,先手动设置环境变量(例如 `export https_proxy=http://localhost:7890 http_proxy=http://localhost:7890`),然后运行:

```bash
scripts/sync-main.sh     # main fast-forward 到上游
scripts/sync-gpui.sh     # gpui merge 上游,modify/delete 冲突自动保留删除
```

详细说明见 [docs/dev/branch-sync.md](docs/dev/branch-sync.md)。

## 许可证

本仓库沿用上游 Zed 的许可证:`LICENSE-APACHE`(Apache-2.0)与 `LICENSE-GPL`(GPL v3)。各 crate 目录内保留各自的 `LICENSE-APACHE` 副本,`crates/gpui` 的 `Cargo.toml` 声明 `license = "Apache-2.0"`。裁剪未改动任何许可证条款,单独使用 gpui 时遵循 Apache-2.0 即可。
