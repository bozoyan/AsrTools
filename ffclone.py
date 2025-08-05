# 终端执行命令：
# cd /Volumes/AI/AI/GPT-SoVITS && conda activate GPTSoVits && ./go-api_v2.command

# API接口代码为：
# http://127.0.0.1:9880/tts?text=输入需要语音合成的内容。&text_lang=zh&ref_audio_path=./output/slicer_opt/F2024.wav&prompt_lang=zh&prompt_text=人家补课补来补去的也就上了个鉴湖，他什么都不补课也能上鉴湖。&text_split_method=cut5&batch_size=1&media_type=wav&streaming_mode=true
# 切换GPT模型
# http://127.0.0.1:9880/set_gpt_weights?weights_path=GPT_weights_v2/f1027-e15.ckpt
# 切换Sovits模型
# http://127.0.0.1:9880/set_sovits_weights?weights_path=SoVITS_weights_v2/f1027_e8_s208.pth


import gradio as gr
import requests
import os
from pathlib import Path
import shutil
from datetime import datetime

def copy_file_to_destination(uploaded_file, destination_dir):
    # 确保目标目录存在
    os.makedirs(destination_dir, exist_ok=True)
    
    # 构建目标文件路径
    dest_path = os.path.join(destination_dir, os.path.basename(uploaded_file))
    
    # 复制文件
    shutil.copy2(uploaded_file, dest_path)
    return dest_path

def generate_audio(text, ref_audio, prompt_text):
    if not text:
        return "请输入要合成的文本！", None
    
    try:
        # 构建API请求URL
        base_url = "http://127.0.0.1:9880/tts"
        params = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": f"./output/slicer_opt/{os.path.basename(ref_audio)}" if ref_audio else "./output/slicer_opt/F2024.wav",
            "prompt_lang": "zh",
            "prompt_text": prompt_text or "人家补课补来补去的也就上了个鉴湖，他什么都不补课也能上鉴湖。",
            "text_split_method": "cut5",
            "batch_size": "1",
            "media_type": "wav",
            "streaming_mode": "true"
        }
        
        # 如果有上传新的音频文件，复制到目标目录
        if ref_audio:
            dest_dir = "/Volumes/AI/AI/GPT-SoVITS/output/slicer_opt"
            copy_file_to_destination(ref_audio, dest_dir)
        
        # 发送API请求
        response = requests.get(base_url, params=params)
        
        if response.status_code == 200:
            # 保存音频文件
            # 生成时间戳
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target_dir = "声音生成"  # 子目录名称
            # 确保目标目录存在（如果不存在则创建）
            os.makedirs(target_dir, exist_ok=True)
            # audio_file = f"ff-{timestamp}.wav"
            audio_file = os.path.join(target_dir, f"ff-{timestamp}.wav")  # 路径拼接
            with open(audio_file, "wb") as f:
                f.write(response.content)
            return "音频生成成功！", audio_file
        else:
            return f"生成失败：{response.status_code}", None
            
    except Exception as e:
        return f"发生错误：{str(e)}", None

def switch_gpt_model():
    try:
        response = requests.get("http://127.0.0.1:9880/set_gpt_weights", 
                              params={"weights_path": "GPT_weights_v2/f1027-e15.ckpt"})
        return "GPT模型切换成功！" if response.status_code == 200 else f"切换失败：{response.status_code}"
    except Exception as e:
        return f"切换错误：{str(e)}"

def switch_sovits_model():
    try:
        response = requests.get("http://127.0.0.1:9880/set_sovits_weights", 
                              params={"weights_path": "SoVITS_weights_v2/f1027_e8_s208.pth"})
        return "Sovits模型切换成功！" if response.status_code == 200 else f"切换失败：{response.status_code}"
    except Exception as e:
        return f"切换错误：{str(e)}"

# 创建界面
with gr.Blocks(title="GPT-SoVITS 语音合成") as demo:
    with gr.Column():
        gr.Markdown("# BOZO 专用声音生成器")
        
        # 修改为一行三列显示
        with gr.Row():
            gpt_btn = gr.Button("切换GPT模型(f1027-e15)")
            sovits_btn = gr.Button("切换Sovits模型(f1027_e8_s208)")
            model_status = gr.Textbox(label="模型切换状态", scale=2)
        
        # 绑定按钮事件
        gpt_btn.click(fn=switch_gpt_model, outputs=model_status)
        sovits_btn.click(fn=switch_sovits_model, outputs=model_status)
        
        # 音频上传和提示文本并排显示
        with gr.Row():
            audio_input = gr.Audio(
                label="上传参考音频文件（可选）",
                type="filepath",
                format="wav"
            )
            prompt_input = gr.Textbox(
                label="提示文本",
                value="人家补课补来补去的也就上了个鉴湖，他什么都不补课也能上鉴湖。",
                placeholder="输入提示文本",
                lines=5
            )
        
        # 文本输入区域，设置更高的输入框
        text_input = gr.Textbox(
            label="请输入要合成的文本",
            placeholder="输入需要语音合成的内容",
            lines=5
        )
        
        # 生成按钮
        generate_btn = gr.Button("生成音频")
        
        # 状态信息和音频输出并排显示
        with gr.Row():
            output_text = gr.Textbox(label="状态信息")
            output_audio = gr.Audio(label="生成的音频")
        
        generate_btn.click(
            fn=generate_audio,
            inputs=[text_input, audio_input, prompt_input],
            outputs=[output_text, output_audio]
        )

# 启动应用
if __name__ == "__main__":
    demo.launch()
