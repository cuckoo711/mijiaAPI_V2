# Android 独立服务测试版

在手机内运行现有 Python 后端、SQLite、加密凭据存储和 Vue 管理台，无需外部服务器。米家云登录、同步和设备控制仍需联网。

## 兼容目标

- Android 7.0 / API 24 起；ARM 32 位 `armeabi-v7a`、ARM 64 位 `arm64-v8a`，另含 `x86`、`x86_64` 供模拟器验证。
- 使用 Python 3.11，避免新 Python 版本仅支持 64 位。原生依赖单独编译；`verify_wheels.py` 核对 ELF 位数与机器架构，构建结果不能替代设备运行验收。
- 管理台需要支持网页模块的 Android System WebView。低于 Chromium 61 时应用会提示更新，服务本身仍可运行；此最低门槛不等于所有界面都已在该版本验收。
- 当前产物为持续维护的 debug 测试签名；GitHub Actions 使用仓库加密 Secret 保留同一签名，可以覆盖升级测试包。不要混用不同签名升级。

## 使用

1. 安装测试 APK，打开应用并点击“启动服务”；按需允许显示常驻服务通知。
2. 服务就绪后点击“打开管理台”，首次使用创建自己的管理员账号，再登录米家。
3. 局域网访问默认关闭。若需其他设备调用 API，停止服务、勾选局域网访问，再启动；其他设备仍需管理员或 API Key 鉴权。
4. 手机上的米家扫码登录，可通过另一台设备打开局域网管理台展示二维码，再用手机米家扫码。
5. 停止或正常升级保留数据；卸载、清除应用数据会删除本机 SQLite 和凭据。测试版暂不提供一键备份与恢复入口。

后台服务使用常驻通知和运行期间的 CPU 唤醒锁；退出界面不等于停止服务。可从应用或通知停止。厂商省电策略、系统强制停止或重启仍可能中断服务；本版未提供开机自启。长期供电与锁屏稳定性需要真机验证。

## 构建

需要 JDK 17、Android SDK 35 / Build Tools 35.0.0、Python 3.11 和 Node.js。Gradle Wrapper 带发行包 SHA256 校验。

原生依赖交叉编译使用 Linux x86_64、NDK 27.3.13750724，以及固定的 Chaquopy 源码提交 `884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41`。Python target 为 `3.11.17-0`。安装 Rust 编译器及 `armv7-linux-androideabi`、`aarch64-linux-android`、`i686-linux-android`、`x86_64-linux-android` 标准库，并将 `rustc`、`cargo` 加入 PATH。

```sh
python3.11 wheels/build.py --chaquopy-source /path/to/chaquopy
python3.11 wheels/vendor.py
python3.11 verify_wheels.py
BUILD_PYTHON=/absolute/path/to/python3.11 sh build.sh
```

`wheels/build.py` 对固定交叉编译器应用两项兼容修正：避免稳定 ABI 库重复创建符号链接，并显式提供 PyO3 交叉配置及 ARMv7 Rust 目标。上游源码或版本改变时需重新审核这些修正。`vendor.py` 预下载纯 Python 依赖，APK 组装时禁用 pip 网络访问。构建产物、wheel 和设备数据均不提交到仓库。

可选环境变量 `MIJIA_MAVEN_MIRROR=https://maven.aliyun.com/repository` 仅为当前构建启用 Maven 镜像，不修改机器全局设置。

APK 位于 `app/build/outputs/apk/<架构>/debug/`：通用包供安装使用，按独立 product flavor 构建的架构包用于兼容性测试。不要改为标准 ABI splits：Python 资源与原生库必须按同一组 ABI 构建。`prepare.py` 只打包指定 Python 源码、前端构建输出及公开模板，不包含 `configs/` 下的运行数据或真实米家凭据。APK 中的 `build-info.json` 记录基础提交和源码内容哈希。

## 自动运行验收

仅在**全新的一次性测试模拟器**中运行，测试会创建虚构管理员与 API Key，不接入真实米家账号：

```sh
adb -s emulator-5580 install -t app/build/outputs/apk/x64/debug/app-x64-debug.apk
adb -s emulator-5580 shell am instrument -w com.cuckoo.mijia.standalone/.SmokeInstrumentation
```

验收覆盖原生 AES、Pydantic、二维码生成、真实 HTTP 服务、前端资源、管理员初始化/登录、API Key 权限与撤销，以及停止重启后的 SQLite 数据保留。ARM 指令转换器上的结果与 ARM 真机结果需分别记录。真实米家登录、同步、物理设备控制、旧系统和长时间后台运行不能由这些离线用例证明。

## 本次测试包验收范围

`3.9.1-android-test.1` 的 ARM 32 位、ARM 64 位、x86、x86_64 和通用包均已在 Android 11 / API 30、WebView 83 的隔离模拟器中完成检查。ARM 两项使用系统指令转换，x86 两项原生执行；解释器位数、APK 内 ABI 资源、签名和哈希分别核对。凭据使用离线虚构数据验证加密及重启后的密钥对保留，未复用服务器的真实米家凭据。

随 APK 提供 `validation-report.json` 和 `SHA256SUMS`。Android 7–10 的实际运行、ARM 真机、真实米家云与设备动作、长时间锁屏，以及 Android 12 及以上的前台服务策略仍待对应设备验证。测试签名包不等于正式稳定发布。

## GitHub 自动构建与发布

推送 `v3.9.1-android-test.1` 这类标签会单独构建、验收并发布 Android 预发布版本。后续常规 `vX.Y.Z` 发布会同时构建桌面程序和 Android 测试 APK，全部通过后统一发布到同一 Release。手动运行 `Android Test APK` 工作流仅构建验收，不创建 Release。

优先安装 `mijia-server-android-universal-<版本>.apk`；确认手机架构后也可选择体积较小的 `arm32` 或 `arm64` 包。CI 附件包含 `ANDROID_SHA256SUMS`、`android-validation.json` 和签名/架构校验报告。ARM 模拟器测试使用指令转换，不能替代真机验证。

构建版本默认跟随 `pyproject.toml`，发布标签必须与后端版本匹配；测试序号支持 1–99。`versionCode` 按主版本、次版本、补丁和测试序号递增，正式版本使用序号 99。仓库 Secret `ANDROID_TEST_KEYSTORE` 保存 Base64 编码的现有测试签名库（标准 Android debug 别名与口令），缺失时构建失败，禁止每次随机换签名。迁移仓库或备份时需单独安全保存该密钥，不能提交到 Git。

Linux CI 从固定提交获取交叉编译器，按 `ci/inputs.json` 的 SHA256 核验 Python target 与依赖源码，使用 NDK 27.3.13750724、Rust 1.99.0 构建原生 wheel。wheel 缓存恢复后仍重新校验 ELF；APK 组装全程使用预下载的 Python wheel。
