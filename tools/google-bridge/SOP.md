# google-bridge SOP（部署 + 启动 + 维护）

> 标准操作流程：怎么把 google-bridge 装起来跑起来。**部署前必读**。

## 触发

任何时候需要部署 / 重启 / 迁移 google-bridge 服务时。

## 步骤

### 1. 前置依赖

| 依赖 | 版本 | 安装 |
|---|---|---|
| Python | 3.8+ | 系统包管理器 |
| Chrome | 100+ | https://googlechromelabs.github.io/chrome-for-testing/ |
| chromedriver | 匹配 Chrome 版本 | 同上 |
| mihomo | 1.18+ | https://github.com/MetaCubeX/mihomo |
| Xvfb | 任意 | `apt install xvfb`（Linux only） |
| Python 库 | 见 requirements.txt | `pip install -r requirements.txt` |

### 2. 配环境变量

```bash
cp example_config.sh .env
vim .env
# 必填：
#   NO1_CHROME_BIN=/path/to/chrome
#   NO1_CHROMEDRIVER_BIN=/path/to/chromedriver
#   NO1_CHROME_UDD=/path/to/chrome_user_data_dir  # 持久 cookies
#   NO1_PROXY=socks5://127.0.0.1:7897  # 或 mihomo 远程地址

source .env
```

**关键**：
- `NO1_CHROME_UDD` 必须是**独立目录**（不能多个实例共享）——共享会互踢
- `NO1_PROXY` 必须可达 —— 这是绕数据中心 IP 的唯一路径

### 3. 启动

```bash
bash start_search_helper.sh
```

启动器自动：
- 检查 / 启动 Xvfb `:99`
- 检查 / 启动 mihomo（如未启动）
- 设置 `DISPLAY=:99` 等环境变量
- 启动 search_helper.py（端口 18799）

### 4. 验证

```bash
# 健康检查
curl http://127.0.0.1:18799/health
# {"ok": true}

# 实际搜索
curl "http://127.0.0.1:18799/search?q=test&num=5&since=7d&vendor=test&role=primary"
# 应返回 JSON，含 results[]
```

### 5. 持续运行

建议用 `nohup` 或 systemd 守护：

```bash
# nohup 方式
nohup bash start_search_helper.sh > /var/log/google-bridge.log 2>&1 &
echo $! > /var/run/google-bridge.pid

# systemd 方式（推荐生产）
cat > /etc/systemd/system/google-bridge.service <<'EOF'
[Unit]
Description=ai-search-stack google-bridge
After=network.target

[Service]
Type=simple
User=search
EnvironmentFile=/home/search/ai-search-stack/tools/google-bridge/.env
ExecStart=/bin/bash /home/search/ai-search-stack/tools/google-bridge/start_search_helper.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now google-bridge
```

## 失败回滚

| 失败现象 | 原因 | 回滚 |
|---|---|---|
| 启动后立即退出 | 缺依赖 / 路径错 | `bash -x start_search_helper.sh` 看哪步失败 |
| `Empty reply` | 端口被占 / Chrome 没起来 | `lsof -i :18799` + `ps aux \| grep chrome` |
| `HTTP 403 / CAPTCHA` | mihomo 节点死了 | 跑 `python3 auto_select_node.py` 切节点 |
| Chrome 频繁崩溃 | UDD 损坏 | 删 UDD 重建（会丢 cookies / trust） |
| `NO1_PROXY` 连不上 | mihomo 没启动 / 端口错 | `curl -x $NO1_PROXY https://example.com` 测试 |
| `OSError: [Errno 24] Too many open files` | fd 耗尽 | `ulimit -n 65535` 提升 |

## 自动化检查

- [ ] `curl http://127.0.0.1:18799/health` 返回 `{"ok": true}`
- [ ] 实际搜索返回非空 `results`
- [ ] mihomo 节点延迟 < 300ms
- [ ] Chrome UDD 大小 > 10MB（有持久 cookies）
- [ ] honeypot.jsonl 持续追加（每 query 一行）

## 反面案例

- ❌ 多个 google-bridge 实例共享一个 UDD → cookies 互踢，全部 CAPTCHA
- ❌ 不用 mihomo（直连 Google） → 100% CAPTCHA
- ❌ 用 `chromedriver` 直接（不用 undetected-chromedriver） → 仍被 Google 识别为 bot
- ❌ `auto_select_node` 跑完不切节点 → 节点死锁时无能为力
- ❌ `pip install undetected-chromedriver` 后不重启 → 旧版还在跑
- ❌ `xvfb-run` 包裹 script 但 DISPLAY 没 export → Chrome 找不到显示器