# VPS 流量监控

一个轻量级 VPS 网页流量监控面板，通过 `http://VPS_IP:9090` 访问。

## 默认配置

- 账号：`admin`
- 密码：`QQqq308008685`
- 端口：`9090`
- 数据库：`traffic.db`

## 功能

- 实时显示上传速度和下载速度
- 实时显示当月上传、下载累计流量
- 支持选择指定月份查看累计上传、下载数据
- 支持查看全部网卡或单个网卡
- 使用 SQLite 持久化流量累计数据
- 支持 systemd 后台运行和开机自启

## 一键部署

在 VPS 上执行：

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

## 防火墙放行

如果 VPS 开启了防火墙，需要放行 `9090` 端口：

```bash
sudo ufw allow 9090/tcp
```

如果使用云厂商安全组，也需要在安全组中放行 TCP `9090`。

## 手动部署

把项目上传到 VPS 后执行：

```bash
cd vps-traffic-monitor
chmod +x install.sh
sudo ./install.sh
```

## 手动运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

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