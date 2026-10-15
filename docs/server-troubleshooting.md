# 服务器排查

- **启动退出**：查看 `docker compose logs --tail=100 panel`。检查 PUBLIC_URL 为 HTTPS、密码哈希有效、`.env` 位于 Compose 同目录。
- **NPM 502**：确认容器健康；若 NPM 在 Docker 中，使用 `compose.npm.yaml` 接入实际 NPM 网络，代理目标为 `baichao-panel:8080`。
- **请求主机不匹配 / 请求来源无效**：PUBLIC_URL 必须等于浏览器中实际使用的管理域名及端口。NPM 保留原始 Host，不要改为容器名。修改后重建容器。
- **登录次数受限**：失败十次后等待五分钟。默认使用直接连接地址限速；NPM 后方用户可能共享限速桶。
- **会话过期**：重新登录；会话最长八小时，服务重启后旧会话失效。
- **GitHub 401/403/404**：检查令牌、Wiki 仓库授权、Contents 写权限和组织授权。发布状态查询需要 Actions 只读。
- **仓库冲突**：导出草稿后重新同步，人工合并。程序不强制覆盖远端。

服务器端口仅供反向代理访问，勿把本地 Windows HTTP 服务改成公网服务。服务器使用独立的 Flask/Gunicorn 登录入口。
