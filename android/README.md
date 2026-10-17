# Android 独立服务测试版

在手机内运行 Python 后端、SQLite、加密凭据存储和 Vue 管理台，无需外部服务器。米家登录、同步和设备控制需要联网。

后端运行在独立的 `:server` 前台服务进程中，管理台通过不导出的同 UID IPC 获取状态和初始化令牌。退出界面不会停止服务。

## 兼容范围

- Android 7.0 / API 24 起；支持 `armeabi-v7a`、`arm64-v8a`，另含供模拟器测试的 `x86`、`x86_64`。
- 使用 Python 3.11；`verify_wheels.py` 核对原生依赖的 ELF 位数与机器架构。
- APK 包含现代与旧版前端，旧内核自动加载兼容包；低于 Chromium 49 时提示更新。
- 测试 APK 使用固定 debug 签名，可以覆盖升级同签名测试包。

优先安装 `mijia-server-android-universal-<版本>.apk`，确认手机架构后也可选择体积较小的 `arm32` 或 `arm64` 包。各版本已检查的环境见 Release 附件 `android-validation.json`、`android-compatibility.json` 和签名/架构报告；文件校验见 `ANDROID_SHA256SUMS`。

## 使用

1. 安装 APK，打开应用并点击“启动服务”，按需允许显示常驻服务通知。
2. 服务就绪后点击“打开管理台”，首次创建管理员账号，再登录米家。
3. 局域网访问默认关闭。需要其他设备调用时，先停止服务、勾选局域网访问，再启动；调用仍需管理员或 API Key 鉴权。
4. 手机米家扫码可借助另一台设备打开局域网管理台展示二维码。
5. 停止或正常升级保留数据；卸载、清除应用数据会删除本机 SQLite 和凭据。测试版暂无一键备份恢复入口。

后台服务使用常驻通知和 CPU 唤醒锁，可从应用或通知停止。锁屏进入 Doze 后系统可能暂停网络；点击“后台运行帮助 → 设置后台运行”并确认系统授权。应用会显示电池优化状态；不支持该入口时可进入应用设置调整。

Android 8 及以上可在 WebView 渲染进程被回收或崩溃后重建管理台。看到“管理台已重置”后重新打开即可，未提交的输入可能丢失，已保存数据保留。Android 7 不支持此系统回调。

专用服务手机建议持续供电。厂商省电策略、强制停止和系统重启仍可能中断服务，本版未提供开机自启。

## 构建

需要 JDK 17、Android SDK 35 / Build Tools 35.0.0、Python 3.11、Node.js 和 npm。Gradle Wrapper 校验发行包 SHA256。

原生依赖交叉编译使用 Linux x86_64、NDK `27.3.13750724`、Chaquopy 固定提交 `884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41`，Python target 为 `3.11.17-0`。安装 Rust 编译器与 `armv7-linux-androideabi`、`aarch64-linux-android`、`i686-linux-android`、`x86_64-linux-android` 标准库，将 `rustc`、`cargo` 加入 PATH。

在 `android/` 目录执行：

```sh
python3.11 wheels/build.py --chaquopy-source /path/to/chaquopy
python3.11 wheels/vendor.py
python3.11 verify_wheels.py
BUILD_PYTHON=/absolute/path/to/python3.11 sh build.sh
```

`wheels/build.py` 对交叉编译器修正稳定 ABI 库重复符号链接，并提供 PyO3 交叉配置及 ARMv7 Rust 目标；升级上游时需复核。`vendor.py` 预下载纯 Python 依赖，APK 组装时禁用 pip 网络访问。可用 `MIJIA_MAVEN_MIRROR=https://maven.aliyun.com/repository` 为本次构建启用 Maven 镜像。

APK 输出到 `app/build/outputs/apk/<架构>/debug/`。架构包使用独立 product flavor；不要改为标准 ABI splits，Python 资源和原生库必须按同一组 ABI 构建。`prepare.py` 只打包指定源码、前端产物和公开模板，排除 `configs/` 运行数据。`build-info.json` 记录基础提交与源码内容哈希；构建产物、wheel 和设备数据不提交到仓库。

## 自动运行测试

以下命令在 `android/` 目录运行，仅用于全新的一次性模拟器，测试会创建虚构管理员和 API Key：

```sh
adb -s emulator-5580 install -t app/build/outputs/apk/x64/debug/app-x64-debug.apk
adb -s emulator-5580 shell am instrument -w com.cuckoo.mijia.standalone/.SmokeInstrumentation
```

测试覆盖原生 AES、Pydantic、二维码生成、HTTP 服务、前端资源、管理员初始化/登录、API Key 权限与撤销，以及重启后的 SQLite 数据保留，不接入真实米家账号。ARM 指令转换结果须与 ARM 真机结果分别记录。

## GitHub 自动构建与发布

推送 `vX.Y.Z-android-test.N` 标签会构建、检查并发布 Android 预发布版本；常规 `vX.Y.Z` 标签同时构建桌面程序与 Android APK，通过检查后统一发布。手动运行 **Android Test APK** 只构建检查，不创建 Release。最新正式版和最新 Android 测试版自动[同步到 Gitee](../deploy/scripts/README.md#3-gitee-release-镜像)。

标签版本须与 `pyproject.toml` 一致，测试序号支持 1–99。`versionCode` 按主版本、次版本、补丁和测试序号递增，正式版使用序号 99。仓库 Secret `ANDROID_TEST_KEYSTORE` 保存 Base64 编码的现有测试签名库，使用标准 Android debug 别名与口令；缺失时构建失败。迁移仓库时需单独安全备份签名库，不能提交到 Git 或随机更换签名。

Linux CI 按 `ci/inputs.json` 的 SHA256 核验 Python target 与依赖源码，使用上述 NDK 和 Rust `1.99.0` 构建 wheel；恢复缓存后仍重新校验 ELF，APK 组装使用预下载的 wheel。

### 兼容检查

发布门禁在 API 24、31、33、34、35、36（Android 7.0、12–16）上检查同一通用 APK，API 24 使用 WebView 53。检查包含：

- 网页登录、导航与解锁后管理台。
- 不附着 instrumentation 的连续 600 秒锁屏 HTTP 探测。
- 后端进程、前台服务、唤醒锁及系统后台授权入口。
- 强制 Doze 与应用 UID 到受控本机端点的网络连接。
- 支持的平台主动终止渲染进程，检查后端、HTTP 与页面恢复。

`android-compatibility.json` 记录环境、APK SHA256、采样和时长，通过后生成发布附件。真实米家登录、同步、设备动作、ARM 真机、厂商省电策略和多日后台稳定性需单独验证。

## 16 KiB 页兼容检查

构建时递归扫描 APK 及 Chaquopy `.imy` 内的 ELF，要求 ARM64 / x86_64 LOAD 段满足 16 KiB 对齐，并运行 `zipalign -c -P 16 4`；RELRO 端点另行记录。

运行检查使用 API 36 的 `google_apis_ps16k` 镜像，要求用户空间页大小为 16384，报告同时记录内核页大小和 WebView 版本。x86_64 镜像可在 4 KiB 内核上模拟 16 KiB 用户空间，仍须执行启动、登录、权限、后台、Doze 和解锁检查。

API 35 的 16 KiB 镜像内置 WebView 124 存在 MemoryInfra 原生崩溃，应用会在创建 WebView 前阻止此组合并提示更新；后端仍可独立启动。模拟器配置至少 4096 MiB 内存，避免首次启动和 WebView 加载时因内存不足回收进程。

## 24 小时锁屏测试

仅用于隔离的一次性模拟器，测试会清空应用数据。在仓库根目录运行：

```sh
python android/ci/test_compatibility.py --serial emulator-5584 --adb-server-port 5039 --apk /path/to/test.apk \
  --output /path/to/evidence --seconds 86400 --expect-page-size 16384 \
  --disposable --expect-console --expect-exemption-ui --full-ui
```

每 30 秒采集 UTC 时间、经过时长、启动标识、系统运行时间、后端 PID、HTTP 就绪、锁屏和唤醒锁状态，原子写入 `compatibility.json`。报告绑定受测 APK 哈希，并分别记录 APK 源提交、测试脚本提交及辅助脚本 SHA256。独立长测报告与 CI 的 600 秒报告分别发布。

### 运行环境

- 用 systemd 分别托管模拟器和测试，模拟器保持前台运行；不要让它们随协调脚本退出而被同一控制组清理。
- 使用专用 ADB 端口，`launch_16k.py --adb-server-port` 与测试参数一致；API 24 启动进程设置相应的 `ANDROID_ADB_SERVER_PORT` 和 `ADB_SERVER_SOCKET`。
- 模拟器控制台使用 5554–5584 内的偶数端口，便于 ADB 重启后发现。
- 共享主机串行执行 16 KiB 与旧系统长测，避免资源竞争。
- ADB 元数据读取和临时 HTTP 转发最多尝试三次，每次超时 10 秒、间隔 1 秒，记录 `transport_failures`；安装、清数据、点击和服务控制不隐式重试。

### 结果判定

HTTP 不可用、后端 PID 或启动标识变化、锁屏/唤醒锁异常会停止测试并保留记录。ADB 采集失败记为 `observation_gap`；恢复后核对启动标识、PID、进程启动时间和运行时间，缺口内的 HTTP 可用性仍为未知。人工重启、清数据或不同进程的观测段分别记录。

`collect_endurance.py` 检查单调时长、UTC 起止、设备运行时间及解锁后管理台，完整 24 小时须达到 86400 秒，末次请求开始时间须在锁屏结束前 5 秒内。不得拼接观测段或将旧 APK 的报告用于新 APK。

测试版可使用 `collect_stability.py --apk ... --review ... --output ...` 生成显式评审报告，绑定同一 APK 和源提交，记录完整 24 小时参考、旧系统观测段、采集异常、人工结束和独立复验；保留原始失败或未知状态。

`review_postflight.py` 先核对安装包 SHA256、PID、boot_id 和进程启动时间，再检查系统授权、Doze、受控网络、HTTP 与解锁后 DOM，不清空数据。最后的 DOM instrumentation 会重新附着应用，报告单独记录此测试动作。
