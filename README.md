# 🎤 AsrTools

<div align="center">

**一款全能的音视频+字幕+语音合成处理工具**

[![Python Version](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/PyQt5-5.15-green)](https://pypi.org/project/PyQt5/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[功能介绍](#-核心功能) • [快速上手](#-快速上手) • [安装指南](#-安装指南) • [更新日志](#-更新日志)

</div>

---

## 🌟 核心功能

AsrTools 是一款基于 **PyQt5** 和 **qfluentwidgets** 的多功能音视频处理工具，集成了语音识别、字幕处理、视频处理和语音合成等多种功能。

### 📝 ASR 字幕识别
- **多引擎支持**：支持 B接口、J接口、K接口等多种 ASR 引擎
- **智能转换**：自动将视频文件转换为音频进行处理
- **多格式导出**：支持生成 `.srt`、`.txt`、`.ass` 字幕文件
- **批量处理**：支持多线程并发处理，默认 3 个线程
- **拖拽支持**：支持拖拽文件或文件夹快速添加

### ✨ SRT 字幕优化
- **智能合并**：自动将碎片化的字幕合并为完整句子
- **LLM 拆分**：利用大语言模型对长句进行语义拆分
- **时间同步**：自动调整字幕时间轴，保持与视频同步
- **中英文支持**：完美处理中英文混合字幕

### 🎬 音视频合并
- **音频合并**：支持 MP3、WAV、OGG、FLAC、AAC、M4A 等格式
- **视频合并**：支持 MP4、AVI、MOV、MKV、TS、FLV 等格式
- **智能策略**：自动选择最佳合并方式（concat 或重新编码）
- **批量处理**：一次处理多个文件，高效快捷

### 📸 视频帧提取
- **首帧提取**：快速获取视频第一帧作为封面
- **尾帧提取**：智能提取视频最后一帧
- **自定义时间**：精确提取指定时间点的视频帧
- **批量处理**：支持文件夹批量提取

### 🔄 视频转换
- **尺寸调整**：自定义视频宽度和高度
- **等比例缩放**：保持原始视频比例
- **高质量编码**：H.264 编码，可调节 CRF 质量参数

### 🎵 视频转音频
- **多格式输出**：MP3、WAV、AAC、FLAC、M4A、OGG
- **质量可调**：支持高质量、中等质量、低质量三种预设
- **批量转换**：快速处理多个视频文件

### 🎙️ 声音生成
- **本地 TTS**：基于 GPT-SoVITS 的文本转语音
- **参考音频**：使用指定音频作为声音参考
- **历史记录**：自动保存生成记录，方便播放查看

### 🤖 API 声音生成（新功能）
- **多密钥支持**：支持配置多个 API 密钥，自动轮询切换
- **队列处理**：当队列满时自动切换密钥重试
- **批量生成**：支持同时生成多个语音任务（最多 5 个并发）
- **实时状态**：显示每个任务的处理状态（准备→提交→等待→处理中→下载→完成）
- **音色选择**：支持多种预设音色，可自定义参考文本
- **任务记录**：完整的生成历史记录，支持播放、打开文件/URL等操作

---

## 🚀 快速上手

### 系统要求
- **Python**: 3.12 或更高版本
- **操作系统**: Windows / macOS / Linux
- **依赖工具**: FFmpeg（用于音视频处理）

### 启动应用

```bash
# 激活虚拟环境（可选）
source venv/bin/activate

# 启动 GUI 界面
python asr_gui.py
```

### 基础操作流程

**1. ASR 字幕识别**
```
选择 ASR 引擎 → 选择导出格式 → 添加音频/视频文件 → 点击"开始处理"
```

**2. SRT 字幕优化**
```
选择 SRT 源文件 → 选择保存路径 → 点击"开始处理"
```

**3. 音视频合并**
```
添加文件（可拖拽排序）→ 选择输出目录 → 点击"开始合并"
```

**4. 视频帧提取**
```
选择视频文件 → 选择输出目录 → 选择帧类型（首帧/尾帧/自定义）→ 点击"开始提取"
```

**5. API 声音生成**
```
选择音色 → 配置密钥文件 → 输入文本 → 点击"生成声音"
```

---

## 🛠️ 安装指南

### 方式一：从源码安装（推荐）

1. **克隆仓库**
```bash
git clone https://github.com/bozoyan/AsrTools.git
cd AsrTools
```

2. **创建虚拟环境**
```bash
conda create -n asrtools python=3.12 -y
conda activate asrtools
```

3. **配置 conda 镜像（可选，加速下载）**
```bash
cat > ~/.condarc << EOF
channels:
  - defaults
show_channel_urls: true
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge
EOF
```

4. **安装依赖**
```bash
# 安装 PyQt5
conda install -y pyqt

# 安装 Python 依赖
pip install -r requirements.txt
```

5. **安装 FFmpeg**
- **Windows**: 下载 [FFmpeg](https://ffmpeg.org/download.html) 并配置环境变量
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

6. **启动程序**
```bash
python asr_gui.py
```

### 方式二：使用可执行文件

下载对应平台的可执行文件，直接运行即可，无需安装 Python 环境。

---

## 📖 功能详解

### ASR 字幕识别

支持多种在线 ASR 引擎，快速将音频/视频转换为字幕文本：

| 引擎 | 说明 | 特点 |
|------|------|------|
| B 接口 | 必剪接口 | 识别准确，速度快 |
| J 接口 | 剪映接口 | 支持长音频 |
| K 接口 | 快手接口 | 免费使用 |

**支持的输入格式**：`.mp3`, `.wav`, `.ogg`, `.mp4`, `.avi`, `.mov`, `.ts` 等

**支持的输出格式**：`.srt`（字幕）, `.txt`（纯文本）, `.ass`（高级字幕）

### SRT 字幕优化

自动将 ASR 生成的碎片化字幕优化为可读性强的完整字幕：

- **智能合并**：将连续的短字幕合并为长句
- **语义拆分**：对过长的句子进行语义分割
- **标点处理**：自动添加和修正标点符号
- **缓存机制**：减少重复请求，提高处理效率

### API 声音生成配置

**1. 配置密钥文件**
创建一个文本文件（如 `keys.txt`），每行一个 API 密钥：
```
sk-xxxxxxxxxxxxxxxxxxxxxxxx
sk-yyyyyyyyyyyyyyyyyyyyyyyy
sk-zzzzzzzzzzzzzzzzzzzzzzzz
```

**2. 配置音色文件**
创建 `slicer_opt.json` 文件，定义可用的音色：
```json
[
    {
        "title": "温柔女声",
        "content": "今天天气真好，我们一起出去玩吧。",
        "filename": "https://example.com/audio1.wav"
    },
    {
        "title": "磁性男声",
        "content": "这是一段用于声音克隆的参考文本。",
        "filename": "https://example.com/audio2.wav"
    }
]
```

**3. 多密钥轮询机制**
- 程序会自动轮询使用所有密钥
- 当某个密钥队列满时，自动切换到下一个密钥
- 最多支持同时 5 个并发任务

---

## 📁 项目结构

```
AsrTools/
├── asr_gui.py              # 主程序 GUI 界面
├── main.py                 # SRT 优化命令行工具
├── requirements.txt        # Python 依赖列表
├── README.md              # 项目说明文档
├── icon.png               # 程序图标
│
├── bk_asr/                # ASR 引擎模块
│   ├── BaseASR.py         # ASR 基类
│   ├── BcutASR.py         # 必剪接口实现
│   ├── JianYingASR.py     # 剪映接口实现
│   ├── KuaiShouASR.py     # 快手接口实现
│   └── WhisperASR.py      # Whisper 接口（待实现）
│
├── ASRData.py             # ASR 数据结构和格式转换
├── split_by_llm.py        # LLM 字幕分段处理
│
├── output/                # 输出文件目录
├── api_voice_history.json # API 语音生成历史记录
└── slicer_opt.json        # 音色配置文件
```

---

## 🔄 更新日志

### v2.1.9 (最新版本)
- 🎨 **优化界面布局**：调整 API 声音生成界面布局，提升用户体验
- 📐 **窗口尺寸**：主窗口大小调整为 1080x780
- 🐛 **修复问题**：修复若干已知问题

### v2.1.8
- 🆕 **多密钥批量生成**：API 声音生成支持多密钥轮询，自动队列切换
- ⚡ **并发处理**：支持最多 5 个并发语音生成任务
- 📊 **实时状态**：新增详细的任务状态显示

### v2.1.0
- 🎵 **音视频合并**：新增音视频批量合并功能
- 🖱️ **拖拽排序**：支持拖拽调整合并顺序

### v1.1.0
- 🎥 **视频文件支持**：支持直接导入视频文件进行 ASR 处理
- 🔄 **自动转换**：视频自动转换为音频进行处理

### v1.0.0
- 🎉 **初始发布**：实现基本的 SRT 文件处理功能

---

## 📬 联系与支持

- **GitHub**: [https://github.com/bozoyan/AsrTools](https://github.com/bozoyan/AsrTools)
- **问题反馈**: [提交 Issue](https://github.com/bozoyan/AsrTools/issues)

---

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=bozoyan/AsrTools&type=Date)](https://star-history.com/#bozoyan/AsrTools&Date)

---

<div align="center">

**感谢您使用 AsrTools！** 🎉

如果觉得这个项目对您有帮助，请给一个 Star ⭐

目前项目的相关调用和 GUI 页面的功能仍在不断完善中...

</div>
