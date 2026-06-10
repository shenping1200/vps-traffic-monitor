# VPS 流量监控

一个轻量级 VPS 网页流量监控面板，通过 `http://VPS_IP:9090` 访问。

## 默认配置

- 账号：`admin`
- 密码：`admin`
- 端口：`9090`
- 数据库：`traffic.db`

## 功能

- 实时显示上传速度和下载速度
- 实时显示当月上传、下载累计流量
- 支持通过年份下拉 + 月份下拉查询历史累计数据
- 支持设置中心修改账号密码、Telegram 报警参数、主机备注
- 支持查看全部网卡或单个网卡
- 支持日流量额度、月流量额度报警
- 支持 Telegram 真实报警与测试发送
- 使用 SQLite 持久化流量累计数据
- 支持 `systemd` 后台运行和开机自启

## 一键部署

推荐直接在 VPS 上执行：

```bash
curl -fsSL https://raw.githubusercontent.com/shenping1200/vps-traffic-monitor/main/install-remote.sh | sudo bash
```

如果服务器没有 `curl`，可以使用：

```bash
wget -qO- https://raw.githubusercontent.com/shenping1200/vps-traffic-monitor/main/install-remote.sh | sudo bash
```

部署完成后访问：

```text
http://你的服务器IP:9090
```

默认账号密码：`admin` / `admin`

## 一键卸载

推荐直接在 VPS 上执行：

```bash
curl -fsSL https://raw.githubusercontent.com/shenping1200/vps-traffic-monitor/main/uninstall.sh | sudo bash
```

如果服务器没有 `curl`，可以使用：

```bash
wget -qO- https://raw.githubusercontent.com/shenping1200/vps-traffic-monitor/main/uninstall.sh | sudo bash
```

卸载会执行以下操作：

- 停止并删除 `vps-traffic-monitor` 服务
- 删除 `/etc/systemd/system/vps-traffic-monitor.service`
- 删除 `/opt/vps-traffic-monitor`
- 重新加载 `systemd`

## Telegram 报警说明

在设置中心中填写以下内容后即可使用真实报警：

- 机器人 `Token`
- `Chat ID` 或群组 ID
- 日流量额度
- 月流量额度
- 报警阈值策略

程序会自动采集当前 VPS 主机名，并在 Telegram 报警消息中带上主机名、备注、IP、当前用量、设置额度、使用比例和触发时间。多台 VPS 可以共用同一个机器人和同一个 `Chat ID` 接收报警。

## 防火墙放行

如果 VPS 开启了防火墙，需要放行 `9090` 端口：

```bash
sudo ufw allow 9090/tcp
```

如果使用云厂商安全组，也需要在安全组中放行 TCP `9090`。

## 常用命令

查看服务状态：

```bash
sudo systemctl status vps-traffic-monitor
```

重启服务：

```bash
sudo systemctl restart vps-traffic-monitor
```

查看日志：

```bash
sudo journalctl -u vps-traffic-monitor -f
```
