#!/bin/bash
# 评估集周跑（回归报警）：每周日21:15跑10任务评估，评分卡投飞书群
# 部署：cp /root/Agent/deploy/agent-eval-weekly.sh /root/.hermes/scripts/ && chmod +x
# 说明：全量评估约13分钟；改提示词/解析器/工具后应另跑 python3 eval/run_eval.py 验证
cd /root/Agent || { echo "ERR: /root/Agent 不存在"; exit 1; }
echo "== Agent评估集周报 $(date '+%Y-%m-%d %H:%M') =="
python3 -u eval/run_eval.py --llm hermes 2>&1 | tail -16
