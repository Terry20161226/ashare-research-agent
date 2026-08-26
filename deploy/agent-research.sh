#!/bin/bash
# A股研究员Agent — 部署版 wrapper（hermes cron --no-agent 模式，stdout直投飞书）
# 部署：cp /root/Agent/deploy/agent-research.sh /root/.hermes/scripts/ && chmod +x /root/.hermes/scripts/agent-research.sh
# 任务来源：/root/Agent/TASK.txt 前3行；首行'!'前缀=手动指定(联动脚本跳过)
# 可选联动：deploy/update_task.py 从A股研究队列(只读)自动挑对象；队列缺失/格式不符自动跳过
cd /root/Agent || { echo "ERR: /root/Agent 不存在"; exit 1; }

python3 deploy/update_task.py 2>/dev/null || echo "(队列联动跳过)"

TASK_FILE=/root/Agent/TASK.txt
if [ -s "$TASK_FILE" ]; then
  mapfile -t TASKS < <(head -3 "$TASK_FILE" | sed 's/^!//')
else
  TASKS=("研究 600519 贵州茅台")
fi

for task in "${TASKS[@]}"; do
  [ -z "$task" ] && continue
  echo "===== 研究任务：$task ====="
  python3 main.py "$task" --llm hermes --verbose --max-steps 12
  echo
done
