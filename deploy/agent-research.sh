#!/bin/bash
# A股研究员Agent（裸循环）— ECS 部署版 wrapper
# 用途：hermes cron --no-agent 模式执行本脚本，stdout 直投飞书群
# 部署：cp /root/Agent/deploy/agent-research.sh /root/.hermes/scripts/ && chmod +x /root/.hermes/scripts/agent-research.sh
# 任务来源：/root/Agent/TASK.txt（存在则读取整行为研究任务），否则默认 600519
cd /root/Agent || { echo "ERR: /root/Agent 不存在"; exit 1; }
TASK_FILE=/root/Agent/TASK.txt
if [ -s "$TASK_FILE" ]; then
  TASK=$(head -1 "$TASK_FILE")
else
  TASK="研究 600519 贵州茅台"
fi
python3 main.py "$TASK" --llm hermes --verbose --max-steps 12
