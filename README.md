# 白潮管理后台 · Baichao Panel

白潮 Wiki 的独立管理工具，提供 **Windows 便携版**和 **Debian / Docker Compose 服务器版**。支持配队视频、推荐组合与来源、矩阵次数、本地或服务器草稿、备份、GitHub 同步、差异预览和发布。

| 仓库 | 职责 |
| --- | --- |
| [baichao-wiki](https://github.com/Reduction77/baichao-wiki) | 公开 Wiki 页面、游戏资料和 GitHub Pages 自动部署 |
| [baichao-panel](https://github.com/Reduction77/baichao-panel) | 管理界面、Windows 程序、服务器后端、部署配置与 Release 安装包 |

管理程序不放进 Wiki 仓库。保存草稿不会改变公开页面，确认发布后才提交 Wiki 资料并触发 Pages 更新。后台关闭时公开 Wiki 仍可访问。

## 下载

打开 [最新 Release](https://github.com/Reduction77/baichao-panel/releases/latest)，Assets 下有两个安装包：

- `baichao-panel-windows-v版本.zip`：Windows x64 EXE 便携包，不需要 Python、Docker 或 Git。
- `baichao-panel-server-v版本.tar.gz`：服务器部署包，包含 Dockerfile、Compose、后端、界面和部署说明，需要服务器能拉取 Python 镜像及构建依赖。

GitHub 自动显示的 Source code 包是仓库源码，不是上述两种安装包。

## Windows 使用

1. 解压 Windows ZIP，双击 `BaichaoWikiAdmin.exe`，浏览器会自动打开。
2. 进入“连接设置”，填写 Wiki 仓库和自己的 GitHub 令牌，保存后“从 GitHub 同步”。
3. 编辑、保存草稿，点击“预览并发布”，核对差异后确认提交。
4. 等待 GitHub Actions 发布成功再刷新 Wiki。

草稿及加密令牌保存在 `%LOCALAPPDATA%\BaichaoWikiAdmin`。旧版 Windows 程序可沿用该目录，升级前先退出旧程序并导出备份。Windows 令牌使用当前账户的 DPAPI 加密，换账户或电脑需要重新填写。

## 服务器部署（Debian 13 / Docker Compose）

建议使用管理域名，例如 `panel.winboard.top`，公开 Wiki 仍使用 `wiki.winboard.top`。管理域名需要单独配置 DNS、NPM 反向代理和 HTTPS。

### 1. 解压与构建

```bash
mkdir -p /opt/baichao-panel
cd /opt/baichao-panel
# 将服务器 Release 安装包上传到这里，再按实际文件名解压：
tar -xzf baichao-panel-server-v1.2.0.tar.gz
cd baichao-panel-server
cp .env.example .env
chmod 600 .env
docker compose build
```

后续版本按对应文件名解压即可。也可以克隆本仓库后，在仓库根目录执行相同的构建操作。

### 2. 设置管理员与 GitHub

生成密码哈希（交互输入，不会显示原密码）：

```bash
docker compose run --rm panel python -m server.manage hash-password
```

编辑 `.env`：

```dotenv
PANEL_PUBLIC_URL=https://panel.winboard.top
PANEL_ADMIN_USER=admin
PANEL_PASSWORD_HASH=填写刚生成的完整scrypt哈希
PANEL_GITHUB_REPO=Reduction77/baichao-wiki
PANEL_GITHUB_BRANCH=main
PANEL_GITHUB_TOKEN=填写自己的细粒度令牌
```

`PANEL_PUBLIC_URL` 必须与实际访问的 HTTPS 管理地址完全一致，不要填公开 Wiki 地址或附加路径。密码至少 12 个字符；服务器不接受默认密码哈希或公开 HTTP 地址。

GitHub 令牌仅授权 **Wiki 仓库**：开启 **Contents 读写**；需要查看自动部署进度时，再开启 **Actions 只读**。不需要授权 Panel 仓库或 Workflows 写权限。令牌从服务器环境读取，不通过浏览器回传或写入导出备份。服务器页面的连接设置只显示状态，修改连接配置需编辑 `.env` 并重建容器。

### 3. 配置 NPM，启动后台

默认 Compose 只开放 `127.0.0.1:8765`。如果 NPM 直接运行在主机上，转发到 `127.0.0.1:8765`。

**如果 NPM 在 Docker 里，推荐共用 Docker 网络：**

1. 用 `docker network ls` 查找 NPM 实际使用的网络。
2. 在 `.env` 追加 `PANEL_NPM_NETWORK=实际网络名`。
3. 使用附带的网络配置启动：

```bash
docker compose -f compose.yaml -f compose.npm.yaml up -d
```

4. NPM 新建 Proxy Host：域名填写管理域名；Scheme 选 `http`；Forward Hostname 填 **`baichao-panel`**；Forward Port 填 **`8080`**。申请证书并启用 Force SSL。

NPM 容器内部的 `127.0.0.1` 指向 NPM 自己，不能用于连接另一个容器。

如果 NPM 在主机上，则只需：

```bash
docker compose up -d
```

等待健康检查后，访问 `.env` 中配置的 HTTPS 地址，使用管理员账户登录。

### 4. 日常管理

登录 → 从 GitHub 同步 → 编辑 → 保存草稿 → 预览差异 → 确认发布 → 等待 Wiki 部署成功。

- Windows 和服务器的草稿分别保存；两端发布前都应同步最新仓库。
- 远端仓库已更新时，后台拒绝覆盖。先导出草稿，再同步并合并修改。
- 同步会替换未发布草稿，请先导出备份。
- 修改 `.env` 后执行与启动时一致的 Compose 命令，并追加 `--force-recreate`。
- 服务只有一个 Gunicorn worker、四个线程；不要手动增加 worker，以免多个进程使用不同草稿状态。

## 数据、备份与维护

Compose 项目固定名为 `baichao-panel`，使用命名卷 `baichao-panel_panel-data` 持久化草稿、最近十份备份、会话密钥及审计日志。更新安装目录不会更换数据卷。**不要使用 `docker compose down -v`，否则会删除卷数据。**

建议先在界面“导出备份”。服务器令牌、管理员密码哈希在 `.env`，须单独妥善备份。Windows 与服务器之间迁移内容时使用导入/导出，不复制 Windows 的加密设置文件。

查看运行状态和日志：

```bash
docker compose ps
docker compose logs --tail=100 panel
```

使用 NPM 网络配置启动的服务，管理时请同样带上 `-f compose.yaml -f compose.npm.yaml`。Docker 日志最多约 6 MB；审计日志最多约 3 MB，均不记录密码、令牌或请求正文。登录会话最长八小时，重启服务后需要重新登录。

更新：下载新版服务器包，保留 `.env`，构建并用相同 Compose 项目启动。回退时使用旧版包重新构建；数据变更前先导出备份。

## 开发、测试与 Release

- Windows 源码：`admin/windows`；服务器入口：`server/app.py`。
- 本地 Windows 源码运行需要 Python 3.11+，双击 `admin/windows/start.bat`。
- 服务器依赖：`pip install -r requirements-server.txt`。
- 测试：`python -m unittest discover -s admin/windows -p "test_app.py"` 和 `python -m unittest discover -s server -p "test_*.py"`。
- Windows 打包：在 Windows x64 安装 `pyinstaller==6.16.0`，运行 `python admin/build_windows_exe.py`。
- 服务器打包：运行 `python scripts/build_server_package.py`。

`VERSION` 是发布版本号。推送到 `main` 后，工作流先检查 Windows/服务器逻辑、构建并测试实际 EXE、构建并启动 Docker 后端，再生成两个包。该版本尚无 Release 时，工作流会创建对应标签和 Release，并附上 Windows ZIP 与服务器 TAR.GZ；已有版本不会覆盖，发布新版请先递增 `VERSION`。

## 版权

《鸣潮》相关文字、数据与游戏素材版权归库洛游戏（KURO GAMES）所有。项目为非官方辅助工具；游戏资料来源及适用要求请以 Wiki 和原视频标注为准。
