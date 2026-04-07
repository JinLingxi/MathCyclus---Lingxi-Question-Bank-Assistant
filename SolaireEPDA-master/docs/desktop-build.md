# 桌面版构建与验证（Windows）

## 前置条件

- Rust（`rustup`）、Node 20+、可访问 **python.org** 与 **bootstrap.pypa.io**（用于下载 embeddable Python 与 get-pip；仅构建机需要）
- Windows：安装 **Visual Studio Build Tools**（含 MSVC），以便 Rust 链接
- **Tauri CLI**（二选一）：在仓库根目录执行 `npm install` 后使用 `npm run tauri:dev`；或全局安装 `cargo install tauri-cli` 后在**仓库根目录**使用 `cargo tauri dev`（不要在 `src-tauri` 子目录里执行）。
- 可选：`pip install maturin`（PrimeBrush PyO3 加速）

## 应用图标（窗口 / 托盘 / 安装包）

- **源图**：仓库根目录 [`icon.png`](../icon.png)（与 `src-tauri/icons/icon.png` 同步），为 **正方形** 主图；[`tauri.conf.json`](../src-tauri/tauri.conf.json) 的 `bundle.icon` 指向 `icons/32x32.png`、`icons/128x128.png`、`icons/icon.ico`。
- **托盘**：[`src-tauri/src/main.rs`](../src-tauri/src/main.rs) 使用 `tray-icon.png` 构建托盘图标。
- **更新流程**：将新的正方形 PNG 覆盖 `src-tauri/icons/icon.png`（须为 **1:1**；若原图为横向矩形，需先裁切或加边），在**仓库根目录**执行：

  ```powershell
  npm install   # 确保有 @tauri-apps/cli
  npx tauri icon .\src-tauri\icons\icon.png
  ```

  会重新生成 `icons/` 下各平台尺寸、`icon.ico`、`icon.icns` 等。

## 嵌入式 Python 运行时（默认打包路径）

正式安装包中的本地服务不再使用 Nuitka 单文件 exe，而是 **Windows embeddable Python** + `pip install` 后的 `site-packages`，目录位于 `src-tauri/runtime/python/`（由脚本生成，体积大，见该目录下 `.gitignore`）。

在仓库根目录执行（或直接使用一键 `.\scripts\build.ps1`，其中已包含此步骤）：

```powershell
.\scripts\stage-python-runtime.ps1
# 强制重新下载并安装：
.\scripts\stage-python-runtime.ps1 -Force
```

脚本会：下载 embeddable zip、启用 `import site`、安装 pip、再 `pip install .` 安装本仓库及依赖。完成后可用下列命令自检（需在仓库根目录已安装的前提下，解释器路径以你本机为准）：

```powershell
.\src-tauri\runtime\python\python.exe -m solaire.desktop_entry --port 8765
```

`tauri.conf.json` 的 `bundle.resources` 包含 `runtime/python/**/*`，将整棵运行时打进 MSI。

## 干净 Conda 环境（仅日常开发推荐，非安装包必需）

在仓库根目录使用 **前缀路径** 创建环境（不污染 base），便于与 `scripts/dev-desktop.ps1`、本地 `pytest` 一致：

```powershell
conda create -p .\.conda-solaire python=3.12 pip -y
$env:PYTHONNOUSERSITE = "1"
.\.conda-solaire\python.exe -m pip install --no-user -e .
```

`.conda-solaire\` 已加入 `.gitignore`。

## 一键构建

在仓库根目录：

```powershell
.\scripts\build.ps1
```

可跳过部分步骤：

```powershell
.\scripts\build.ps1 -SkipRust              # 跳过 maturin
.\scripts\build.ps1 -SkipPythonRuntime     # 跳过嵌入式 Python 筹备（仅前端 + Tauri；本地服务需自行处理）
.\scripts\build.ps1 -SkipNuitka            # 与 -SkipPythonRuntime 相同（旧参数名，已弃用）
.\scripts\build.ps1 -SkipTauri             # 不打包安装包
```

若直接执行 `npm run tauri:build`，需**先**成功运行 `.\scripts\stage-python-runtime.ps1`，否则 `bundle.resources` 下仅有占位文件，安装包内本地服务不可用。

### MSI 打包失败：`timeout: global`（下载 WiX 超时）

打 **MSI** 时 Tauri 会从 GitHub 下载 **WiX Toolset**（`wix314-binaries.zip`）。网络慢或被墙时，内置下载容易超时并报错 `failed to bundle project timeout: global`。

**做法一（推荐）**：先预下载到 Tauri 使用的缓存目录（与 `tauri-bundler` 一致：`%LOCALAPPDATA%\cache\tauri\WixTools314`）：

```powershell
.\scripts\prepare-wix-tools.ps1
# 缓存损坏或需重装：
.\scripts\prepare-wix-tools.ps1 -Force
```

`.\scripts\build.ps1` 在缺少该目录时会**自动**尝试执行上述脚本（使用较长 HTTP 超时）。若仍失败，可浏览器下载同一 zip 后解压到 `%LOCALAPPDATA%\cache\tauri\WixTools314`，确保目录内直接可见 `candle.exe`、`light.exe` 等。

**做法二**：为 Tauri 打包器配置 GitHub 资源镜像（环境变量，见上游 `tauri-bundler` 的 `http_utils`）：

- `TAURI_BUNDLER_TOOLS_GITHUB_MIRROR`：将完整 GitHub 资源 URL 映射到镜像的基础地址；或
- `TAURI_BUNDLER_TOOLS_GITHUB_MIRROR_TEMPLATE`：按模板替换 `owner/repo/tag/file`。

配置后重新执行 `npm run tauri:build` 或 `.\scripts\build.ps1`。

## 集成验证建议

1. 安装生成的 MSI（或运行 `src-tauri\target\release\solaire-desktop.exe`）。
2. 若启动长时间无响应：主进程会等待本地服务 `/api/health`；嵌入式 Python 的 **stderr** 会追加写入 **`%TEMP%\solaire-desktop-python.log`**（可查看是否 import 失败、端口占用等）。
3. 确认无额外控制台窗口；应用最小化后在系统托盘可见。
4. 在欢迎页使用「新建项目」或「打开项目」绑定工作目录后，确认组卷/题库等页面可正常使用。
5. 关闭应用后再次打开，「最近打开」中应出现该项目。
6. PDF 导出仍依赖本机安装的 **PDF 排版环境**（常见为 MiKTeX 或 TeX Live）。安装包**不包含**该环境；未安装时，组卷页会显示引导条，并可在 Windows 上尝试「一键安装」（调用系统自带的应用安装器安装 MiKTeX）。受限网络或策略禁止时，请用户按引导打开官方页面手动安装，完成后在组卷页点「重新检测」。

## 开发调试（Tauri + Vite）

### 打完包后 `tauri dev` 卡死 / 白屏很久？

**开发模式**（debug）下，应用默认**不**拉起 `src-tauri/runtime/python` 内的嵌入式解释器，而是连接 `beforeDevCommand` 启动的 **Uvicorn 127.0.0.1:8000**，避免冷启动慢、占满健康检查等待或与开发后端冲突。

若你**刻意**要在 `tauri dev` 里调试与安装包一致的嵌入式运行时，请先执行 `.\scripts\stage-python-runtime.ps1`，再设置环境变量 **`SOLAIRE_USE_SIDECAR=1`** 后启动。

必须在**仓库根目录**（与 `src-tauri` 同级）运行 Tauri，否则 CLI 找不到工程。

```powershell
cd D:\Git\AmazingEducation   # 换成你的仓库根路径
npm install                  # 首次：安装 @tauri-apps/cli
npm run tauri:dev
```

或已安装 Rust 版 CLI 时：

```powershell
cargo install tauri-cli      # 仅需执行一次
cd D:\Git\AmazingEducation
cargo tauri dev
```

`tauri dev` 会在**仓库根目录**执行 `scripts/dev-desktop.ps1`（勿写成 `../scripts/`，否则会指到仓库外）：后台 Uvicorn（8000）+ 前台 Vite（5173）。

若出现 `error: no such command: tauri`，说明尚未安装 Tauri CLI，请使用上面的 `npm install` + `npm run tauri:dev`，或执行 `cargo install tauri-cli`。

## 历史说明

仓库内仍保留 [`scripts/nuitka-solaire.ps1`](../scripts/nuitka-solaire.ps1) 供参考，**默认一键构建已不再调用**。若需恢复 Nuitka 单文件侧车，需自行改回 `build.ps1` 与 `main.rs` 逻辑。
