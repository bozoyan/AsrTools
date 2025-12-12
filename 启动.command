#!/bin/bash
# chmod +x 启动.command
# 切换到项目目录
cd "/Volumes/AI/AI/AsrTools"

# 激活 python 环境
source venv/bin/activate
conda activate asrtools

# 打印启动信息
echo "AsrTools：智能语音转文字工具 启动中..."

# 启动 asr_gui.py，并指定可用端口和模型路径
python asr_gui.py \
  2>&1 | tee logs/output.log

# 等待几秒以确保服务启动完成
sleep 5

# 打印完成信息
echo "AsrTools：智能语音转文字工具 已启动，请查看日志文件：/Volumes/AI/AI/AsrTools/logs/output.log"
