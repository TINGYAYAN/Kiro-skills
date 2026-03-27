# Web 控制台

启动：

```bash
cd /Users/yanye/code/test拨号/_tools
python3 web_console/app.py
```

如果 8765 端口被占用：

```bash
cd /Users/yanye/code/test拨号/_tools
python3 web_console/app.py --port 8766
```

打开：

```text
http://127.0.0.1:8765
```

当前功能：

- 选择项目
- 单条生成
- 批量生成
- 查看编译结果
- 查看部署结果
- 查看历史记录
- 管理 session / 证书 / 飞书表

说明：

- 单条与批量任务都复用现有 `pipeline.py` / `batch_runner.py`
- 默认勾选静默执行，不发飞书通知
- 所有任务日志保存在 `web_console/runtime/`
