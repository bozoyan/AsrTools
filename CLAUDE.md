# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**AsrTools** 是一个基于 **PyQt5** 和 **qfluentwidgets** 的音频语音识别(ASR)和字幕处理工具，当前版本为 **V2.0.0**。项目使用 Python 3.12 开发。激活 python 环境: source venv/bin/activate

## 文档按版本号命名
### 所有的安装文档，测试说明，开发总结，功能说明，完成报告，项目文件清单，任务完成总结之类的md文档全部按照版本号命名，保存到API文件夹内。不要放到项目根目录下。

### 核心功能

1. **ASR 字幕识别** - 支持多种ASR接口（必剪、剪映、快手等）
2. **SRT 字幕优化** - 使用LLM进行字幕分段优化
3. **声音生成** - 基于GPT-SoVITS的语音合成

### 技术架构

- **GUI框架**: PyQt5 + qfluentwidgets (Fluent设计风格)
- **多线程处理**: QThreadPool 和 QRunnable 实现并发ASR处理
- **ASR模块化**: bk_asr/ 目录下各接口独立实现
- **字幕处理**: ASRData.py 提供统一的数据结构和格式转换

## 开发环境配置

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行程序
```bash
python asr_gui.py \
  2>&1 | tee logs/output.log
```

### SRT优化处理
```bash
python main.py --srt_path input.srt --save_path output.srt
```

## 代码架构

### 主要模块

- **asr_gui.py** - 主界面和各功能模块实现
- **main.py** - SRT字幕优化的命令行处理逻辑
- **ASRData.py** - ASR数据结构定义和格式转换
- **bk_asr/** - ASR接口实现目录
  - BaseASR.py - ASR基类
  - BcutASR.py - 必剪接口实现
  - JianYingASR.py - 剪映接口实现
  - KuaiShouASR.py - 快手接口实现
  - WhisperASR.py - Whisper接口实现
- **split_by_llm.py** - LLM字幕分段处理

### 界面结构

主窗口使用 FluentWindow 架构，左侧导航栏包含：
1. ASR 字幕 - 音频/视频文件语音识别
2. SRT 优化 - 字幕文件智能优化
3. 声音生成 - 文本转语音
4. 关于开源 - 项目信息和GitHub链接

### 多线程处理

使用 QThreadPool 管理工作线程，ASR处理通过 ASRWorker 类实现：
- 最大并发线程数: 3
- 支持文件拖拽和批量处理
- 实时状态更新和错误处理

## 开发指导


### 添加新ASR接口

1. 在 bk_asr/ 目录下创建新的ASR类
2. 继承 BaseASR 类并实现 run() 方法
3. 在 asr_gui.py 的 ASRWorker.run() 中添加接口选择逻辑

### 添加新功能模块

1. 创建新的 QWidget 子类实现功能界面
2. 在 MainWindow.__init__ 中使用 addSubInterface 添加到导航栏
3. 使用 QThreadPool 和 QRunnable 处理耗时任务

### 文件处理模式

- 支持拖拽文件和文件夹
- 自动识别音频/视频格式
- 使用 ffmpeg 进行视频到音频转换
- 输出文件保存在原文件同目录

### 错误处理

- 使用 InfoBar 组件显示用户友好的错误信息
- 工作线程异常通过 signals.errno 传递
- 详细的日志记录便于调试

## 常用开发任务

### 调试ASR接口问题
检查对应ASR类的实现，注意网络请求和响应解析逻辑。

### 优化界面性能
确保耗时操作在单独线程中执行，避免阻塞UI线程。

### 添加新的字幕格式支持
在 ASRData.py 中添加新的转换方法，如 to_ass() 等。