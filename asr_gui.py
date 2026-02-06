import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import webbrowser

# FIX: 修复中文路径报错 https://github.com/bozoyan/AsrTools/issues/18  设置QT_QPA_PLATFORM_PLUGIN_PATH 
plugin_path = os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path

from PyQt5.QtCore import Qt, QRunnable, QThreadPool, QObject, pyqtSignal as Signal, pyqtSlot as Slot, QSize, QThread, QTimer, \
    pyqtSignal
from PyQt5.QtGui import QCursor, QColor, QFont, QIcon
import requests
from datetime import datetime
import json

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QTableWidgetItem, QHeaderView, QSizePolicy)
from qfluentwidgets import (ComboBox, PushButton, LineEdit, TableWidget, FluentIcon as FIF,
                            Action, RoundMenu, InfoBar, InfoBarPosition,
                            FluentWindow, BodyLabel, MessageBox, TextEdit, Dialog, SegmentedWidget)

from bk_asr.BcutASR import BcutASR
from bk_asr.JianYingASR import JianYingASR
from bk_asr.KuaiShouASR import KuaiShouASR

# 设置日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class WorkerSignals(QObject):
    finished = Signal(str, str)
    errno = Signal(str, str)
    progress = Signal(int, str, str)  # (行号, 状态, 消息) 用于显示每个任务的进度


class ASRWorker(QRunnable):
    """ASR处理工作线程"""
    def __init__(self, file_path, asr_engine, export_format):
        super().__init__()
        self.file_path = file_path
        self.asr_engine = asr_engine
        self.export_format = export_format
        self.signals = WorkerSignals()

        self.audio_path = None

    @Slot()
    def run(self):
        try:
            use_cache = True
            
            # 检查文件类型,如果不是音频则转换
            logging.info("[+]正在进ffmpeg转换")
            audio_exts = ['.mp3', '.wav']
            if not any(self.file_path.lower().endswith(ext) for ext in audio_exts):
                temp_audio = self.file_path.rsplit(".", 1)[0] + ".mp3"
                if not video2audio(self.file_path, temp_audio):
                    raise Exception("音频转换失败，确保安装ffmpeg")
                self.audio_path = temp_audio
            else:
                self.audio_path = self.file_path
            
            # 根据选择的 ASR 引擎实例化相应的类
            if self.asr_engine == 'B 接口':
                asr = BcutASR(self.audio_path, use_cache=use_cache)
            elif self.asr_engine == 'J 接口':
                asr = JianYingASR(self.audio_path, use_cache=use_cache)
            elif self.asr_engine == 'K 接口':
                asr = KuaiShouASR(self.audio_path, use_cache=use_cache)
            elif self.asr_engine == 'Whisper':
                # from bk_asr.WhisperASR import WhisperASR
                # asr = WhisperASR(self.file_path, use_cache=use_cache)
                raise NotImplementedError("WhisperASR 暂未实现")
            else:
                raise ValueError(f"未知的 ASR 引擎: {self.asr_engine}")

            logging.info(f"开始处理文件: {self.file_path} 使用引擎: {self.asr_engine}")
            result = asr.run()
            
            # 根据导出格式选择转换方法
            save_ext = self.export_format.lower()
            if save_ext == 'srt':
                result_text = result.to_srt()
            elif save_ext == 'ass':
                result_text = result.to_ass()
            elif save_ext == 'txt':
                result_text = result.to_txt()
                
            logging.info(f"完成处理文件: {self.file_path} 使用引擎: {self.asr_engine}")
            save_path = self.file_path.rsplit(".", 1)[0] + "." + save_ext
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(result_text)
            self.signals.finished.emit(self.file_path, result_text)
        except Exception as e:
            logging.error(f"处理文件 {self.file_path} 时出错: {str(e)}")
            self.signals.errno.emit(self.file_path, f"处理时出错: {str(e)}")

class UpdateCheckerThread(QThread):
    msg = pyqtSignal(str, str, str)  # 用于发送消息的信号

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from check_update import check_update, check_internet_connection
            # 检查互联网连接
            if not check_internet_connection():
                self.msg.emit("错误", "无法连接到互联网，请检查网络连接。", "")
                return
            # 检查更新
            config = check_update(self)
            if config:
                if config['fource']:
                    self.msg.emit("更新", "检测到新版本，请下载最新版本。", config['update_download_url'])
                else:
                    self.msg.emit("可更新", "检测到新版本，请下载最新版本。", config['update_download_url'])
        except Exception:
            pass


class ASRWidget(QWidget):
    """ASR处理界面"""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.max_threads = 3  # 设置最大线程数
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(self.max_threads)
        self.processing_queue = []
        self.workers = {}  # 维护文件路径到worker的映射


    def init_ui(self):
        layout = QVBoxLayout(self)

        # ASR引擎选择区域
        engine_layout = QHBoxLayout()
        engine_label = BodyLabel("选择接口:", self)
        engine_label.setFixedWidth(70)
        self.combo_box = ComboBox(self)
        self.combo_box.addItems(['B 接口', 'J 接口', 'K 接口', 'Whisper'])
        engine_layout.addWidget(engine_label)
        engine_layout.addWidget(self.combo_box)
        layout.addLayout(engine_layout)

        # 导出格式选择区域 
        format_layout = QHBoxLayout()
        format_label = BodyLabel("导出格式:", self)
        format_label.setFixedWidth(70)
        self.format_combo = ComboBox(self)
        self.format_combo.addItems(['SRT', 'TXT', 'ASS'])
        format_layout.addWidget(format_label)
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)

        # 文件选择区域
        file_layout = QHBoxLayout()
        self.file_input = LineEdit(self)
        self.file_input.setPlaceholderText("拖拽文件或文件夹到这里")
        self.file_input.setReadOnly(True)
        self.file_button = PushButton("选择文件", self)
        self.file_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(self.file_button)
        layout.addLayout(file_layout)

        # 文件列表表格
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['文件名', '状态'])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.table)

        # 设置表格列的拉伸模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 100)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 处理按钮
        self.process_button = PushButton("开始处理", self)
        self.process_button.clicked.connect(self.process_files)
        self.process_button.setEnabled(False)  # 初始禁用
        layout.addWidget(self.process_button)

        self.setAcceptDrops(True)

    def select_file(self):
        """选择文件对话框"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频或视频文件", "",
                                                "Media Files (*.mp3 *.wav *.ogg *.mp4 *.avi *.mov *.ts)")
        for file in files:
            self.add_file_to_table(file)
        self.update_start_button_state()

    def add_file_to_table(self, file_path):
        """将文件添加到表格中"""
        if self.find_row_by_file_path(file_path) != -1:
            InfoBar.warning(
                title='文件已存在',
                content=f"文件 {os.path.basename(file_path)} 已经添加到列表中。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        item_filename = self.create_non_editable_item(os.path.basename(file_path))
        item_status = self.create_non_editable_item("未处理")
        item_status.setForeground(QColor("gray"))
        self.table.setItem(row_count, 0, item_filename)
        self.table.setItem(row_count, 1, item_status)
        item_filename.setData(Qt.UserRole, file_path)

    def create_non_editable_item(self, text):
        """创建不可编辑的表格项"""
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def show_context_menu(self, pos):
        """显示右键菜单"""
        current_row = self.table.rowAt(pos.y())
        if current_row < 0:
            return

        self.table.selectRow(current_row)

        menu = RoundMenu(parent=self)
        reprocess_action = Action(FIF.SYNC, "重新处理")
        delete_action = Action(FIF.DELETE, "删除任务")
        open_dir_action = Action(FIF.FOLDER, "打开文件目录")
        menu.addActions([reprocess_action, delete_action, open_dir_action])

        delete_action.triggered.connect(self.delete_selected_row)
        open_dir_action.triggered.connect(self.open_file_directory)
        reprocess_action.triggered.connect(self.reprocess_selected_file)

        menu.exec(QCursor.pos())

    def delete_selected_row(self):
        """删除选中的行"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            file_path = self.table.item(current_row, 0).data(Qt.UserRole)
            if file_path in self.workers:
                worker = self.workers[file_path]
                worker.signals.finished.disconnect(self.update_table)
                worker.signals.errno.disconnect(self.handle_error)
                # QThreadPool 不支持直接终止线程，通常需要设计任务可中断
                # 这里仅移除引用
                self.workers.pop(file_path, None)
            self.table.removeRow(current_row)
            self.update_start_button_state()

    def open_file_directory(self):
        """打开文件所在目录"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            current_item = self.table.item(current_row, 0)
            if current_item:
                file_path = current_item.data(Qt.UserRole)
                directory = os.path.dirname(file_path)
                try:
                    if platform.system() == "Windows":
                        os.startfile(directory)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", directory])
                    else:
                        subprocess.Popen(["xdg-open", directory])
                except Exception as e:
                    InfoBar.error(
                        title='无法打开目录',
                        content=str(e),
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=3000,
                        parent=self
                    )

    def reprocess_selected_file(self):
        """重新处理选中的文件"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            file_path = self.table.item(current_row, 0).data(Qt.UserRole)
            status = self.table.item(current_row, 1).text()
            if status == "处理中":
                InfoBar.warning(
                    title='当前文件正在处理中',
                    content="请等待当前文件处理完成后再重新处理。",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
                return
            self.add_to_queue(file_path)

    def add_to_queue(self, file_path):
        """将文件添加到处理队列并更新状态"""
        self.processing_queue.append(file_path)
        self.process_next_in_queue()

    def process_files(self):
        """处理所有未处理的文件"""
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).text() == "未处理":
                file_path = self.table.item(row, 0).data(Qt.UserRole)
                self.processing_queue.append(file_path)
        self.process_next_in_queue()

    def process_next_in_queue(self):
        """处理队列中的下一个文件"""
        while self.thread_pool.activeThreadCount() < self.max_threads and self.processing_queue:
            file_path = self.processing_queue.pop(0)
            if file_path not in self.workers:
                self.process_file(file_path)

    def process_file(self, file_path):
        """处理单个文件"""
        selected_engine = self.combo_box.currentText()
        selected_format = self.format_combo.currentText()
        worker = ASRWorker(file_path, selected_engine, selected_format)
        worker.signals.finished.connect(self.update_table)
        worker.signals.errno.connect(self.handle_error)
        self.thread_pool.start(worker)
        self.workers[file_path] = worker

        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("处理中")
            status_item.setForeground(QColor("orange"))
            self.table.setItem(row, 1, status_item)
            self.update_start_button_state()

    def update_table(self, file_path, result):
        """更新表格中文件的处理状态"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            item_status = self.create_non_editable_item("已处理")
            item_status.setForeground(QColor("green"))
            self.table.setItem(row, 1, item_status)

            InfoBar.success(
                title='处理完成',
                content=f"文件 {self.table.item(row, 0).text()} 已处理完成",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=1500,
                parent=self
            )

        self.workers.pop(file_path, None)
        self.process_next_in_queue()
        self.update_start_button_state()

    def handle_error(self, file_path, error_message):
        """处理错误信息"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            item_status = self.create_non_editable_item("错误")
            item_status.setForeground(QColor("red"))
            self.table.setItem(row, 1, item_status)

            InfoBar.error(
                title='处理出错',
                content=error_message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

        self.workers.pop(file_path, None)
        self.process_next_in_queue()
        self.update_start_button_state()

    def find_row_by_file_path(self, file_path):
        """根据文件路径查找表格中的行号"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.data(Qt.UserRole) == file_path:
                return row
        return -1

    def update_start_button_state(self):
        """根据文件列表更新开始处理按钮的状态"""
        has_unprocessed = any(
            self.table.item(row, 1).text() == "未处理"
            for row in range(self.table.rowCount())
        )
        self.process_button.setEnabled(has_unprocessed)

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽释放事件"""
        supported_formats = ('.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',  # 音频格式
                           '.mp4', '.avi', '.mov', '.ts', '.mkv', '.wmv', '.flv', '.webm', '.rmvb')  # 视频格式
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file in files:
            if os.path.isdir(file):
                for root, dirs, files_in_dir in os.walk(file):
                    for f in files_in_dir:
                        if f.lower().endswith(supported_formats):
                            self.add_file_to_table(os.path.join(root, f))
            elif file.lower().endswith(supported_formats):
                self.add_file_to_table(file)
        self.update_start_button_state()


class SrtOptimizerWorker(QRunnable):
    """SRT优化工作线程"""
    def __init__(self, srt_path, save_path):
        super().__init__()
        self.srt_path = srt_path
        self.save_path = save_path
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            logging.info(f"开始优化SRT文件: {self.srt_path}")
            # 使用 sys.executable 确保我们用的是当前环境的 python
            command = [
                sys.executable, 'main.py',
                '--srt_path', self.srt_path,
                '--save_path', self.save_path
            ]
            # 在Windows上，隐藏命令行窗口
            startupinfo = None
            if platform.system() == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace', startupinfo=startupinfo)
            
            logging.info(f"SRT文件优化完成: {self.save_path}")
            self.signals.finished.emit(self.srt_path, f"优化完成, 已保存到 {self.save_path}")
        except subprocess.CalledProcessError as e:
            error_output = e.stderr or e.stdout
            logging.error(f"优化SRT文件 {self.srt_path} 时出错: {error_output}")
            self.signals.errno.emit(self.srt_path, f"优化时出错: {error_output}")
        except Exception as e:
            logging.error(f"优化SRT文件 {self.srt_path} 时出错: {str(e)}")
            self.signals.errno.emit(self.srt_path, f"优化时出错: {str(e)}")


class VideoFrameWorker(QRunnable):
    """视频帧提取工作线程"""

    def __init__(self, video_path, output_dir, frame_type='first', timestamp='00:00:00'):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.frame_type = frame_type  # 'first', 'last', 'custom'
        self.timestamp = timestamp  # 具体时间戳，如 '00:00:10'
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            import os
            import subprocess
            from pathlib import Path

            # 确保输出目录存在
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            # 生成输出文件名和提取时间
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            
            if self.frame_type == 'first':
                suffix = "_首帧"
                seek_time = '00:00:00'
            elif self.frame_type == 'last':
                suffix = "_尾帧"
                # 获取视频总时长
                cmd_duration = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'default=noprint_wrappers=1:nokey=1', self.video_path]
                result = subprocess.run(cmd_duration, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if result.returncode == 0:
                    total_seconds = float(result.stdout.strip())
                    # 减去1秒作为尾帧时间（保持为数值类型）
                    seek_seconds = max(0, total_seconds - 1)
                    # 转换为 HH:MM:SS 格式
                    hours = int(seek_seconds // 3600)
                    minutes = int((seek_seconds % 3600) // 60)
                    seconds = int(seek_seconds % 60)
                    seek_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    seek_time = '00:00:00'
            else:  # custom
                suffix = f"_{self.timestamp}帧"
                seek_time = self.timestamp
            
            output_path = os.path.join(self.output_dir, f"{video_name}{suffix}.jpg")

            # ffmpeg命令提取指定帧
            cmd = [
                'ffmpeg',
                '-i', self.video_path,
                '-vframes', '1',
                '-q:v', '2',
                '-y',
                '-ss', seek_time,
                output_path
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )

            if result.returncode == 0:
                self.signals.finished.emit(self.video_path, f"成功提取: {os.path.basename(self.video_path)} -> {os.path.basename(output_path)}")
            else:
                self.signals.errno.emit(self.video_path, f"提取失败: {result.stderr}")

        except Exception as e:
            self.signals.errno.emit(self.video_path, f"处理出错: {str(e)}")


class VideoResizeWorker(QRunnable):
    """视频尺寸转换工作线程"""

    def __init__(self, video_path, output_dir, width=None, height=None, maintain_aspect=True):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.width = width
        self.height = height
        self.maintain_aspect = maintain_aspect
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            import os
            import subprocess
            from pathlib import Path

            # 确保输出目录存在
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            # 生成输出文件名
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            output_path = os.path.join(self.output_dir, f"{video_name}_resized.mp4")

            # 构建ffmpeg命令
            cmd = ['ffmpeg', '-i', self.video_path]

            # 设置视频尺寸参数
            if self.maintain_aspect:
                if self.width:
                    # 只设置宽度，高度自动等比例
                    cmd.extend(['-vf', f'scale={self.width}:-2'])
                elif self.height:
                    # 只设置高度，宽度自动等比例
                    cmd.extend(['-vf', f'scale=-2:{self.height}'])
            else:
                # 设置具体的宽度和高度
                if self.width and self.height:
                    cmd.extend(['-vf', f'scale={self.width}:{self.height}'])

            # 添加其他参数
            cmd.extend([
                '-c:v', 'libx264',     # 使用H.264编码
                '-preset', 'medium',   # 编码速度与质量平衡
                '-crf', '23',         # 质量参数（越小质量越高）
                '-c:a', 'copy',       # 音频直接复制
                '-y',                  # 覆盖输出文件
                output_path
            ])

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )

            if result.returncode == 0:
                size_info = ""
                if self.width:
                    size_info += f"宽度:{self.width}"
                if self.height:
                    if size_info:
                        size_info += ", "
                    size_info += f"高度:{self.height}"

                self.signals.finished.emit(self.video_path, f"成功转换: {os.path.basename(self.video_path)} -> {os.path.basename(output_path)} ({size_info})")
            else:
                self.signals.errno.emit(self.video_path, f"转换失败: {result.stderr}")

        except Exception as e:
            self.signals.errno.emit(self.video_path, f"处理出错: {str(e)}")


class VideoToAudioWorker(QRunnable):
    """视频转音频工作线程"""

    def __init__(self, video_path, output_dir, audio_format='mp3', audio_quality=2):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.audio_format = audio_format.lower()
        self.audio_quality = audio_quality  # 音频质量参数
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            import os
            import subprocess
            from pathlib import Path

            # 确保输出目录存在
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            # 生成输出文件名
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            output_path = os.path.join(self.output_dir, f"{video_name}.{self.audio_format}")

            # 构建ffmpeg命令
            cmd = [
                'ffmpeg',
                '-i', self.video_path,
                '-vn',                  # 不要视频流
                '-acodec', self._get_audio_codec(),  # 音频编码器
            ]

            # 根据格式添加质量参数
            if self.audio_format == 'mp3':
                cmd.extend(['-q:a', str(self.audio_quality)])  # MP3质量 (0-9, 0最好)
            elif self.audio_format == 'wav':
                # WAV是无损格式，不需要质量参数
                pass
            elif self.audio_format == 'aac':
                cmd.extend(['-b:a', '192k'])  # AAC比特率
            elif self.audio_format == 'flac':
                # FLAC是无损格式
                pass

            cmd.extend(['-y', output_path])

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )

            if result.returncode == 0:
                self.signals.finished.emit(self.video_path, f"成功转换: {os.path.basename(self.video_path)} -> {os.path.basename(output_path)}")
            else:
                self.signals.errno.emit(self.video_path, f"转换失败: {result.stderr}")

        except Exception as e:
            self.signals.errno.emit(self.video_path, f"处理出错: {str(e)}")

    def _get_audio_codec(self):
        """根据格式获取对应的音频编码器"""
        codec_map = {
            'mp3': 'libmp3lame',
            'wav': 'pcm_s16le',
            'aac': 'aac',
            'flac': 'flac',
            'm4a': 'aac',
            'ogg': 'libvorbis'
        }
        return codec_map.get(self.audio_format, 'libmp3lame')


class TTSWorker(QRunnable):
    """TTS处理工作线程"""

    def __init__(self, text, ref_audio_path, prompt_text, prompt_lang):
        super().__init__()
        self.text = text
        self.ref_audio_path = ref_audio_path
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}.wav"
            save_path = output_dir / filename

            url = "http://127.0.0.1:9880/tts"
            params = {
                "text": self.text,
                "text_lang": "zh",
                "ref_audio_path": self.ref_audio_path,
                "prompt_text": self.prompt_text,
                "prompt_lang": self.prompt_lang,
            }
            logging.info(f"[+]正在请求TTS API: {url} with params: {params}")
            response = requests.get(url, params=params, stream=True)

            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        f.write(chunk)
                logging.info(f"[+]音频文件已保存到: {save_path}")
                self.signals.finished.emit(str(save_path), self.text)
            else:
                error_msg = f"API请求失败，状态码: {response.status_code}, 内容: {response.text}"
                logging.error(error_msg)
                self.signals.errno.emit("API_ERROR", error_msg)

        except requests.exceptions.RequestException as e:
            error_msg = f"调用TTS API时网络错误: {e}"
            logging.error(error_msg)
            self.signals.errno.emit("NETWORK_ERROR", error_msg)
        except Exception as e:
            error_msg = f"处理TTS时发生未知错误: {e}"
            logging.error(error_msg)
            self.signals.errno.emit("UNKNOWN_ERROR", error_msg)


class VideoFrameWidget(QWidget):
    """视频第一帧提取界面"""

    def __init__(self):
        super().__init__()
        self.frame_type = 'first'  # 默认提取首帧
        self.timestamp = '00:00:00'  # 默认时间戳
        self.init_ui()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(3)  # 同时最多处理3个视频
        self.processing_files = set()
        # 初始化按钮样式
        self.set_frame_type('first')

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 源文件选择区域
        source_layout = QHBoxLayout()
        source_label = BodyLabel("源文件:", self)
        source_label.setFixedWidth(70)
        self.source_input = LineEdit(self)
        self.source_input.setPlaceholderText("拖拽视频文件或文件夹到这里")
        self.source_input.setReadOnly(True)
        self.source_button = PushButton("选择文件", self)
        self.source_button.clicked.connect(self.select_source)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(self.source_button)
        layout.addLayout(source_layout)

        # 输出目录选择区域
        output_layout = QHBoxLayout()
        output_label = BodyLabel("输出目录:", self)
        output_label.setFixedWidth(70)
        self.output_input = LineEdit(self)
        self.output_input.setPlaceholderText("默认保存到 output 目录")
        self.output_input.setText(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output'))
        self.output_input.setReadOnly(True)
        self.output_button = PushButton("选择目录", self)
        self.output_button.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_button)
        layout.addLayout(output_layout)

        # 帧选择区域
        frame_label = BodyLabel("帧选择:", self)
        layout.addWidget(frame_label)
        
        frame_layout = QHBoxLayout()
        
        # 首帧按钮
        self.first_frame_btn = PushButton("首帧", self)
        self.first_frame_btn.setCheckable(True)
        self.first_frame_btn.clicked.connect(lambda: self.set_frame_type('first'))
        frame_layout.addWidget(self.first_frame_btn)

        # 尾帧按钮
        self.last_frame_btn = PushButton("尾帧", self)
        self.last_frame_btn.setCheckable(True)
        self.last_frame_btn.clicked.connect(lambda: self.set_frame_type('last'))
        frame_layout.addWidget(self.last_frame_btn)

        # 具体时间帧按钮
        self.custom_frame_btn = PushButton("具体时间帧", self)
        self.custom_frame_btn.setCheckable(True)
        self.custom_frame_btn.clicked.connect(lambda: self.set_frame_type('custom'))
        frame_layout.addWidget(self.custom_frame_btn)
        
        # 时间输入框
        self.time_input = LineEdit(self)
        self.time_input.setPlaceholderText("00:00:10")
        self.time_input.setMaximumWidth(100)
        self.time_input.setEnabled(False)  # 默认禁用
        self.time_input.editingFinished.connect(self.on_time_changed)
        frame_layout.addWidget(self.time_input)
        
        frame_layout.addStretch()
        layout.addLayout(frame_layout)
        
        # 文件列表表格
        table_label = BodyLabel("文件列表:", self)
        layout.addWidget(table_label)
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['文件名', '状态'])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.table)

        # 设置表格列的拉伸模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 120)

        # 日志显示区域
        log_label = BodyLabel("处理日志:", self)
        layout.addWidget(log_label)
        self.log_text = TextEdit(self)
        self.log_text.setFixedHeight(150)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        # 处理按钮
        self.process_button = PushButton("开始提取", self)
        self.process_button.clicked.connect(self.process_videos)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)

        self.setAcceptDrops(True)

    def select_source(self):
        """选择源文件或文件夹"""
        # 创建一个选择对话框让用户选择文件或文件夹
        dialog = Dialog("选择源文件类型", "请选择要添加的类型：", self)
        dialog.yesButton.setText("选择文件")
        dialog.cancelButton.setText("选择文件夹")

        if dialog.exec():
            # 选择文件
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择视频文件", "",
                "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.ts)"
            )
            for file in files:
                self.add_file_to_table(file)
        else:
            # 选择文件夹
            folder = QFileDialog.getExistingDirectory(self, "选择包含视频的文件夹")
            if folder:
                self.add_videos_from_folder(folder)

        self.update_process_button_state()

    def select_output_dir(self):
        """选择输出目录"""
        folder = QFileDialog.getExistingDirectory(self, "选择图片保存目录")
        if folder:
            self.output_input.setText(folder)
            self.update_process_button_state()
    
    def set_frame_type(self, frame_type):
        """设置帧类型"""
        self.frame_type = frame_type

        # 定义按钮样式
        active_style = """
            PushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                min-width: 80px;
            }
            PushButton:hover {
                background-color: #106ebe;
            }
        """
        inactive_style = """
            PushButton {
                background-color: #f0f0f0;
                color: #333333;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                padding: 8px 16px;
                min-width: 80px;
            }
            PushButton:hover {
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
            }
        """

        # 更新按钮状态和样式
        self.first_frame_btn.setChecked(frame_type == 'first')
        self.first_frame_btn.setStyleSheet(active_style if frame_type == 'first' else inactive_style)

        self.last_frame_btn.setChecked(frame_type == 'last')
        self.last_frame_btn.setStyleSheet(active_style if frame_type == 'last' else inactive_style)

        self.custom_frame_btn.setChecked(frame_type == 'custom')
        self.custom_frame_btn.setStyleSheet(active_style if frame_type == 'custom' else inactive_style)

        # 启用或禁用时间输入框
        self.time_input.setEnabled(frame_type == 'custom')

        # 如果是自定义时间，更新时间戳
        if frame_type == 'custom':
            time_text = self.time_input.text()
            if time_text:
                self.timestamp = time_text
        else:
            self.timestamp = '00:00:00'

    def on_time_changed(self):
        """时间输入框编辑完成事件"""
        text = self.time_input.text().strip()
        if self.frame_type == 'custom' and text:
            # 如果输入是纯数字（秒数），自动转换为 HH:MM:SS 格式
            if ':' not in text and text.isdigit():
                total_seconds = int(text)
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                self.time_input.setText(formatted_time)
                self.timestamp = formatted_time
            # 如果已经是 HH:MM:SS 格式，验证后使用
            elif len(text) == 8 and text.count(':') == 2:
                parts = text.split(':')
                try:
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
                        self.timestamp = text
                except ValueError:
                    pass

    def add_videos_from_folder(self, folder):
        """从文件夹添加所有视频文件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')

        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(video_extensions):
                    full_path = os.path.join(root, file)
                    self.add_file_to_table(full_path)

    def add_file_to_table(self, file_path):
        """将文件添加到表格中"""
        if self.find_row_by_file_path(file_path) != -1:
            InfoBar.warning(
                title='文件已存在',
                content=f"文件 {os.path.basename(file_path)} 已经添加到列表中。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        item_filename = self.create_non_editable_item(os.path.basename(file_path))
        item_status = self.create_non_editable_item("未处理")
        item_status.setForeground(QColor("gray"))
        self.table.setItem(row_count, 0, item_filename)
        self.table.setItem(row_count, 1, item_status)
        item_filename.setData(Qt.UserRole, file_path)

    def create_non_editable_item(self, text):
        """创建不可编辑的表格项"""
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def show_context_menu(self, pos):
        """显示右键菜单"""
        current_row = self.table.rowAt(pos.y())
        if current_row < 0:
            return

        self.table.selectRow(current_row)
        menu = RoundMenu(parent=self)
        delete_action = Action(FIF.DELETE, "删除任务")
        menu.addAction(delete_action)
        delete_action.triggered.connect(self.delete_selected_row)
        menu.exec(QCursor.pos())

    def delete_selected_row(self):
        """删除选中的行"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            file_path = self.table.item(current_row, 0).data(Qt.UserRole)
            if file_path in self.processing_files:
                InfoBar.warning(
                    title='正在处理',
                    content="该文件正在处理中，无法删除。",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
                return
            self.table.removeRow(current_row)
            self.update_process_button_state()

    def find_row_by_file_path(self, file_path):
        """根据文件路径查找表格中的行号"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == file_path:
                return row
        return -1

    def update_process_button_state(self):
        """更新处理按钮状态"""
        has_files = self.table.rowCount() > 0
        has_output = bool(self.output_input.text())
        self.process_button.setEnabled(has_files and has_output)

    def process_videos(self):
        """处理所有视频文件"""
        output_dir = self.output_input.text()
        if not output_dir:
            InfoBar.warning("请选择输出目录", parent=self)
            return

        # 检查ffmpeg是否可用
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            InfoBar.error("FFmpeg未找到", "请先安装ffmpeg", parent=self)
            return

        # 处理所有文件（无论之前的状态如何），支持重复提取不同帧
        for row in range(self.table.rowCount()):
            file_path = self.table.item(row, 0).data(Qt.UserRole)

            # 检查文件是否正在处理中
            if file_path in self.processing_files:
                continue

            # 更新状态为处理中
            status_item = self.create_non_editable_item("处理中")
            status_item.setForeground(QColor("orange"))
            self.table.setItem(row, 1, status_item)

            # 添加到处理集合
            self.processing_files.add(file_path)

            # 添加日志
            frame_type_name = {'first': '首帧', 'last': '尾帧', 'custom': f'{self.timestamp}帧'}[self.frame_type]
            self.add_log(f"开始提取{frame_type_name}: {os.path.basename(file_path)}")

            # 创建工作线程
            worker = VideoFrameWorker(file_path, output_dir, self.frame_type, self.timestamp)
            worker.signals.finished.connect(self.on_processing_finished)
            worker.signals.errno.connect(self.on_processing_error)
            self.thread_pool.start(worker)

    def on_processing_finished(self, file_path, message):
        """处理完成回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("已完成")
            status_item.setForeground(QColor("green"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"✅ {message}")

        InfoBar.success(
            title='处理完成',
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_processing_error(self, file_path, error_message):
        """处理错误回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("错误")
            status_item.setForeground(QColor("red"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"❌ {os.path.basename(file_path)}: {error_message}")

        InfoBar.error(
            title='处理出错',
            content=f"{os.path.basename(file_path)}: {error_message}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def add_log(self, message):
        """添加日志消息"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽释放事件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')
        urls = event.mimeData().urls()

        for url in urls:
            file_path = url.toLocalFile()
            if os.path.isdir(file_path):
                # 如果是文件夹，添加其中的所有视频文件
                self.add_videos_from_folder(file_path)
            elif file_path.lower().endswith(video_extensions):
                # 如果是视频文件，直接添加
                self.add_file_to_table(file_path)

        self.update_process_button_state()


class VideoConverterWidget(QWidget):
    """视频尺寸转换界面"""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(2)  # 同时最多处理2个视频（转换比较耗时）
        self.processing_files = set()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 源文件选择区域
        source_layout = QHBoxLayout()
        source_label = BodyLabel("源文件:", self)
        source_label.setFixedWidth(70)
        self.source_input = LineEdit(self)
        self.source_input.setPlaceholderText("拖拽视频文件或文件夹到这里")
        self.source_input.setReadOnly(True)
        self.source_button = PushButton("选择文件", self)
        self.source_button.clicked.connect(self.select_source)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(self.source_button)
        layout.addLayout(source_layout)

        # 输出目录选择区域
        output_layout = QHBoxLayout()
        output_label = BodyLabel("输出目录:", self)
        output_label.setFixedWidth(70)
        self.output_input = LineEdit(self)
        self.output_input.setPlaceholderText("选择转换后视频保存目录")
        self.output_input.setReadOnly(True)
        self.output_button = PushButton("选择目录", self)
        self.output_button.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_button)
        layout.addLayout(output_layout)

        # 转换设置区域
        settings_label = BodyLabel("转换设置:", self)
        layout.addWidget(settings_label)

        # 尺寸设置布局
        size_layout = QHBoxLayout()

        # 宽度设置
        width_layout = QVBoxLayout()
        width_label = BodyLabel("宽度 (像素):", self)
        self.width_input = LineEdit(self)
        self.width_input.setPlaceholderText="留空表示自动计算"
        width_layout.addWidget(width_label)
        width_layout.addWidget(self.width_input)

        # 高度设置
        height_layout = QVBoxLayout()
        height_label = BodyLabel("高度 (像素):", self)
        self.height_input = LineEdit(self)
        self.height_input.setPlaceholderText="留空表示自动计算"
        height_layout.addWidget(height_label)
        height_layout.addWidget(self.height_input)

        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)

        # 等比例复选框
        aspect_layout = QVBoxLayout()
        self.aspect_check = ComboBox(self)
        self.aspect_check.addItems(['保持等比例', '自定义尺寸'])
        self.aspect_check.setCurrentIndex(0)
        aspect_label = BodyLabel("尺寸模式:", self)
        aspect_layout.addWidget(aspect_label)
        aspect_layout.addWidget(self.aspect_check)

        size_layout.addLayout(aspect_layout)
        layout.addLayout(size_layout)

        # 文件列表表格
        table_label = BodyLabel("文件列表:", self)
        layout.addWidget(table_label)
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['文件名', '状态'])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.table)

        # 设置表格列的拉伸模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 120)

        # 日志显示区域
        log_label = BodyLabel("处理日志:", self)
        layout.addWidget(log_label)
        self.log_text = TextEdit(self)
        self.log_text.setFixedHeight(120)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        # 处理按钮
        self.process_button = PushButton("开始转换", self)
        self.process_button.clicked.connect(self.process_videos)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)

        self.setAcceptDrops(True)

        # 连接等比例复选框信号
        self.aspect_check.currentIndexChanged.connect(self.on_aspect_mode_changed)

    def on_aspect_mode_changed(self):
        """等比例模式改变时的处理"""
        is_custom = self.aspect_check.currentText() == '自定义尺寸'
        if not is_custom:
            # 保持等比例模式，至少需要宽度或高度其中一个
            self.add_log("保持等比例模式：只需设置宽度或高度其中一个")
        else:
            # 自定义尺寸模式，可以同时设置宽度和高度
            self.add_log("自定义尺寸模式：可以同时设置宽度和高度")

    def select_source(self):
        """选择源文件或文件夹"""
        dialog = Dialog("选择源文件类型", "请选择要添加的类型：", self)
        dialog.yesButton.setText("选择文件")
        dialog.cancelButton.setText("选择文件夹")

        if dialog.exec():
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择视频文件", "",
                "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.ts)"
            )
            for file in files:
                self.add_file_to_table(file)
        else:
            folder = QFileDialog.getExistingDirectory(self, "选择包含视频的文件夹")
            if folder:
                self.add_videos_from_folder(folder)

        self.update_process_button_state()

    def select_output_dir(self):
        """选择输出目录"""
        folder = QFileDialog.getExistingDirectory(self, "选择转换后视频保存目录")
        if folder:
            self.output_input.setText(folder)
            self.update_process_button_state()

    def add_videos_from_folder(self, folder):
        """从文件夹添加所有视频文件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')

        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(video_extensions):
                    full_path = os.path.join(root, file)
                    self.add_file_to_table(full_path)

    def add_file_to_table(self, file_path):
        """将文件添加到表格中"""
        if self.find_row_by_file_path(file_path) != -1:
            InfoBar.warning(
                title='文件已存在',
                content=f"文件 {os.path.basename(file_path)} 已经添加到列表中。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        item_filename = self.create_non_editable_item(os.path.basename(file_path))
        item_status = self.create_non_editable_item("未处理")
        item_status.setForeground(QColor("gray"))
        self.table.setItem(row_count, 0, item_filename)
        self.table.setItem(row_count, 1, item_status)
        item_filename.setData(Qt.UserRole, file_path)

    def create_non_editable_item(self, text):
        """创建不可编辑的表格项"""
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def show_context_menu(self, pos):
        """显示右键菜单"""
        current_row = self.table.rowAt(pos.y())
        if current_row < 0:
            return

        self.table.selectRow(current_row)
        menu = RoundMenu(parent=self)
        delete_action = Action(FIF.DELETE, "删除任务")
        menu.addAction(delete_action)
        delete_action.triggered.connect(self.delete_selected_row)
        menu.exec(QCursor.pos())

    def delete_selected_row(self):
        """删除选中的行"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            file_path = self.table.item(current_row, 0).data(Qt.UserRole)
            if file_path in self.processing_files:
                InfoBar.warning(
                    title='正在处理',
                    content="该文件正在处理中，无法删除。",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
                return
            self.table.removeRow(current_row)
            self.update_process_button_state()

    def find_row_by_file_path(self, file_path):
        """根据文件路径查找表格中的行号"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == file_path:
                return row
        return -1

    def update_process_button_state(self):
        """更新处理按钮状态"""
        has_files = self.table.rowCount() > 0
        has_output = bool(self.output_input.text())
        self.process_button.setEnabled(has_files and has_output)

    def get_conversion_params(self):
        """获取转换参数"""
        width = None
        height = None
        maintain_aspect = self.aspect_check.currentText() == '保持等比例'

        try:
            width_text = self.width_input.text().strip()
            if width_text:
                width = int(width_text)
                if width <= 0:
                    raise ValueError("宽度必须大于0")
        except ValueError:
            InfoBar.error("参数错误", "宽度必须是正整数", parent=self)
            return None

        try:
            height_text = self.height_input.text().strip()
            if height_text:
                height = int(height_text)
                if height <= 0:
                    raise ValueError("高度必须大于0")
        except ValueError:
            InfoBar.error("参数错误", "高度必须是正整数", parent=self)
            return None

        # 检查参数有效性
        if maintain_aspect and not width and not height:
            InfoBar.warning("参数不足", "保持等比例模式下至少需要设置宽度或高度", parent=self)
            return None

        if not maintain_aspect and (not width or not height):
            InfoBar.warning("参数不足", "自定义尺寸模式下需要同时设置宽度和高度", parent=self)
            return None

        return width, height, maintain_aspect

    def process_videos(self):
        """处理所有视频文件"""
        output_dir = self.output_input.text()
        if not output_dir:
            InfoBar.warning("请选择输出目录", parent=self)
            return

        # 获取转换参数
        params = self.get_conversion_params()
        if params is None:
            return

        width, height, maintain_aspect = params

        # 检查ffmpeg是否可用
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            InfoBar.error("FFmpeg未找到", "请先安装ffmpeg", parent=self)
            return

        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).text() == "未处理":
                file_path = self.table.item(row, 0).data(Qt.UserRole)

                # 更新状态
                status_item = self.create_non_editable_item("处理中")
                status_item.setForeground(QColor("orange"))
                self.table.setItem(row, 1, status_item)

                # 添加到处理集合
                self.processing_files.add(file_path)

                # 添加日志
                size_info = f"宽度:{width if width else '自动'}"
                if height:
                    size_info += f", 高度:{height}"
                self.add_log(f"开始处理: {os.path.basename(file_path)} ({size_info})")

                # 创建工作线程
                worker = VideoResizeWorker(file_path, output_dir, width, height, maintain_aspect)
                worker.signals.finished.connect(self.on_processing_finished)
                worker.signals.errno.connect(self.on_processing_error)
                self.thread_pool.start(worker)

    def on_processing_finished(self, file_path, message):
        """处理完成回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("已完成")
            status_item.setForeground(QColor("green"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"✅ {message}")

        InfoBar.success(
            title='转换完成',
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_processing_error(self, file_path, error_message):
        """处理错误回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("错误")
            status_item.setForeground(QColor("red"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"❌ {os.path.basename(file_path)}: {error_message}")

        InfoBar.error(
            title='转换出错',
            content=f"{os.path.basename(file_path)}: {error_message}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def add_log(self, message):
        """添加日志消息"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽释放事件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')
        urls = event.mimeData().urls()

        for url in urls:
            file_path = url.toLocalFile()
            if os.path.isdir(file_path):
                # 如果是文件夹，添加其中的所有视频文件
                self.add_videos_from_folder(file_path)
            elif file_path.lower().endswith(video_extensions):
                # 如果是视频文件，直接添加
                self.add_file_to_table(file_path)

        self.update_process_button_state()


class VideoToAudioWidget(QWidget):
    """视频转音频界面"""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(3)  # 同时最多处理3个视频
        self.processing_files = set()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 源文件选择区域
        source_layout = QHBoxLayout()
        source_label = BodyLabel("源文件:", self)
        source_label.setFixedWidth(70)
        self.source_input = LineEdit(self)
        self.source_input.setPlaceholderText("拖拽视频文件或文件夹到这里")
        self.source_input.setReadOnly(True)
        self.source_button = PushButton("选择文件", self)
        self.source_button.clicked.connect(self.select_source)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_input)
        source_layout.addWidget(self.source_button)
        layout.addLayout(source_layout)

        # 输出目录选择区域
        output_layout = QHBoxLayout()
        output_label = BodyLabel("输出目录:", self)
        output_label.setFixedWidth(70)
        self.output_input = LineEdit(self)
        self.output_input.setPlaceholderText("选择音频文件保存目录")
        self.output_input.setReadOnly(True)
        self.output_button = PushButton("选择目录", self)
        self.output_button.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_button)
        layout.addLayout(output_layout)

        # 音频格式设置区域
        format_layout = QHBoxLayout()
        format_label = BodyLabel("音频格式:", self)
        format_label.setFixedWidth(70)
        self.format_combo = ComboBox(self)
        self.format_combo.addItems(['MP3', 'WAV', 'AAC', 'FLAC', 'M4A', 'OGG'])
        self.format_combo.setCurrentText('MP3')
        format_layout.addWidget(format_label)
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)

        # 音频质量设置区域
        quality_layout = QHBoxLayout()
        quality_label = BodyLabel("音频质量:", self)
        quality_label.setFixedWidth(70)
        self.quality_combo = ComboBox(self)
        self.quality_combo.addItems(['高质量 (0)', '中等质量 (2)', '低质量 (5)'])
        self.quality_combo.setCurrentIndex(1)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_combo)
        layout.addLayout(quality_layout)

        # 文件列表表格
        table_label = BodyLabel("文件列表:", self)
        layout.addWidget(table_label)
        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['文件名', '状态'])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.table)

        # 设置表格列的拉伸模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 120)

        # 日志显示区域
        log_label = BodyLabel("处理日志:", self)
        layout.addWidget(log_label)
        self.log_text = TextEdit(self)
        self.log_text.setFixedHeight(120)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        # 处理按钮
        self.process_button = PushButton("开始转换", self)
        self.process_button.clicked.connect(self.process_videos)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)

        self.setAcceptDrops(True)

    def select_source(self):
        """选择源文件或文件夹"""
        dialog = Dialog("选择源文件类型", "请选择要添加的类型：", self)
        dialog.yesButton.setText("选择文件")
        dialog.cancelButton.setText("选择文件夹")

        if dialog.exec():
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择视频文件", "",
                "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm *.ts)"
            )
            for file in files:
                self.add_file_to_table(file)
        else:
            folder = QFileDialog.getExistingDirectory(self, "选择包含视频的文件夹")
            if folder:
                self.add_videos_from_folder(folder)

        self.update_process_button_state()

    def select_output_dir(self):
        """选择输出目录"""
        folder = QFileDialog.getExistingDirectory(self, "选择音频文件保存目录")
        if folder:
            self.output_input.setText(folder)
            self.update_process_button_state()

    def add_videos_from_folder(self, folder):
        """从文件夹添加所有视频文件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')

        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(video_extensions):
                    full_path = os.path.join(root, file)
                    self.add_file_to_table(full_path)

    def add_file_to_table(self, file_path):
        """将文件添加到表格中"""
        if self.find_row_by_file_path(file_path) != -1:
            InfoBar.warning(
                title='文件已存在',
                content=f"文件 {os.path.basename(file_path)} 已经添加到列表中。",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        item_filename = self.create_non_editable_item(os.path.basename(file_path))
        item_status = self.create_non_editable_item("未处理")
        item_status.setForeground(QColor("gray"))
        self.table.setItem(row_count, 0, item_filename)
        self.table.setItem(row_count, 1, item_status)
        item_filename.setData(Qt.UserRole, file_path)

    def create_non_editable_item(self, text):
        """创建不可编辑的表格项"""
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def show_context_menu(self, pos):
        """显示右键菜单"""
        current_row = self.table.rowAt(pos.y())
        if current_row < 0:
            return

        self.table.selectRow(current_row)
        menu = RoundMenu(parent=self)
        delete_action = Action(FIF.DELETE, "删除任务")
        menu.addAction(delete_action)
        delete_action.triggered.connect(self.delete_selected_row)
        menu.exec(QCursor.pos())

    def delete_selected_row(self):
        """删除选中的行"""
        current_row = self.table.currentRow()
        if current_row >= 0:
            file_path = self.table.item(current_row, 0).data(Qt.UserRole)
            if file_path in self.processing_files:
                InfoBar.warning(
                    title='正在处理',
                    content="该文件正在处理中，无法删除。",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
                return
            self.table.removeRow(current_row)
            self.update_process_button_state()

    def find_row_by_file_path(self, file_path):
        """根据文件路径查找表格中的行号"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == file_path:
                return row
        return -1

    def update_process_button_state(self):
        """更新处理按钮状态"""
        has_files = self.table.rowCount() > 0
        has_output = bool(self.output_input.text())
        self.process_button.setEnabled(has_files and has_output)

    def get_audio_quality(self):
        """获取音频质量参数"""
        quality_text = self.quality_combo.currentText()
        if "高质量" in quality_text:
            return 0
        elif "中等质量" in quality_text:
            return 2
        else:
            return 5

    def process_videos(self):
        """处理所有视频文件"""
        output_dir = self.output_input.text()
        if not output_dir:
            InfoBar.warning("请选择输出目录", parent=self)
            return

        # 获取转换参数
        audio_format = self.format_combo.currentText().lower()
        audio_quality = self.get_audio_quality()

        # 检查ffmpeg是否可用
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            InfoBar.error("FFmpeg未找到", "请先安装ffmpeg", parent=self)
            return

        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).text() == "未处理":
                file_path = self.table.item(row, 0).data(Qt.UserRole)

                # 更新状态
                status_item = self.create_non_editable_item("处理中")
                status_item.setForeground(QColor("orange"))
                self.table.setItem(row, 1, status_item)

                # 添加到处理集合
                self.processing_files.add(file_path)

                # 添加日志
                self.add_log(f"开始处理: {os.path.basename(file_path)} -> {audio_format.upper()} 格式")

                # 创建工作线程
                worker = VideoToAudioWorker(file_path, output_dir, audio_format, audio_quality)
                worker.signals.finished.connect(self.on_processing_finished)
                worker.signals.errno.connect(self.on_processing_error)
                self.thread_pool.start(worker)

    def on_processing_finished(self, file_path, message):
        """处理完成回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("已完成")
            status_item.setForeground(QColor("green"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"✅ {message}")

        InfoBar.success(
            title='转换完成',
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_processing_error(self, file_path, error_message):
        """处理错误回调"""
        row = self.find_row_by_file_path(file_path)
        if row != -1:
            status_item = self.create_non_editable_item("错误")
            status_item.setForeground(QColor("red"))
            self.table.setItem(row, 1, status_item)

        # 从处理集合移除
        self.processing_files.discard(file_path)

        # 添加日志
        self.add_log(f"❌ {os.path.basename(file_path)}: {error_message}")

        InfoBar.error(
            title='转换出错',
            content=f"{os.path.basename(file_path)}: {error_message}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    def add_log(self, message):
        """添加日志消息"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽释放事件"""
        import os
        video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.ts')
        urls = event.mimeData().urls()

        for url in urls:
            file_path = url.toLocalFile()
            if os.path.isdir(file_path):
                # 如果是文件夹，添加其中的所有视频文件
                self.add_videos_from_folder(file_path)
            elif file_path.lower().endswith(video_extensions):
                # 如果是视频文件，直接添加
                self.add_file_to_table(file_path)

        self.update_process_button_state()


class VoiceApiWidget(QWidget):
    """声音API生成界面"""
    HISTORY_FILE = Path("gpt_sovits_history.json")

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1)  # 同时只处理一个生成任务
        self.history = []
        self.load_history()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 多行文本输入框
        self.text_input = TextEdit(self)
        self.text_input.setPlaceholderText("在此输入需要合成语音的文本...")
        self.text_input.setFixedHeight(150)
        layout.addWidget(self.text_input)

        # 历史记录表格
        history_label = BodyLabel("历史记录:", self)
        layout.addWidget(history_label)
        self.history_table = TableWidget(self)
        self.history_table.setColumnCount(3)
        self.history_table.setHorizontalHeaderLabels(['文本', '文件名', '操作'])
        self.history_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.show_context_menu)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.setWordWrap(True)
        layout.addWidget(self.history_table)

        # 声音生成按钮
        self.generate_button = PushButton("生成声音", self)
        self.generate_button.clicked.connect(self.generate_voice)
        layout.addWidget(self.generate_button)

    def load_history(self):
        if self.HISTORY_FILE.exists():
            try:
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
                for item in self.history:
                    self.add_history_item_to_table(item['text'], item['filename'])
            except (IOError, json.JSONDecodeError) as e:
                logging.error(f"加载历史记录失败: {e}")
                self.history = []

    def save_history(self):
        try:
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=4)
        except IOError as e:
            logging.error(f"保存历史记录失败: {e}")

    def add_history_item_to_table(self, text, filename):
        row_count = self.history_table.rowCount()
        self.history_table.insertRow(row_count)

        # 文本
        text_item = QTableWidgetItem(text)
        text_item.setFlags(text_item.flags() & ~Qt.ItemIsEditable)
        self.history_table.setItem(row_count, 0, text_item)

        # 文件名
        filename_item = QTableWidgetItem(os.path.basename(filename))
        filename_item.setFlags(filename_item.flags() & ~Qt.ItemIsEditable)
        self.history_table.setItem(row_count, 1, filename_item)
        filename_item.setData(Qt.UserRole, filename) # 存储完整路径

        # 播放按钮
        play_button = PushButton(FIF.PLAY, "播放")
        play_button.clicked.connect(lambda _, r=row_count: self.play_audio(r))
        self.history_table.setCellWidget(row_count, 2, play_button)
        self.history_table.resizeRowsToContents()

    def play_audio(self, row):
        filename = self.history_table.item(row, 1).data(Qt.UserRole)
        if os.path.exists(filename):
            try:
                if platform.system() == "Windows":
                    os.startfile(filename)
                elif platform.system() == "Darwin": # macOS
                    subprocess.Popen(["open", filename])
                else: # linux
                    subprocess.Popen(["xdg-open", filename])
            except Exception as e:
                InfoBar.error('播放失败', f'无法播放文件: {e}', parent=self)
        else:
            InfoBar.warning('文件不存在', f'音频文件 {filename} 不存在。', parent=self)

    def generate_voice(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            InfoBar.warning('内容为空', '请输入需要合成的文本。', parent=self)
            return

        # TODO: 让用户可以自定义这些参数
        ref_audio_path = "./output/slicer_opt/F2024.wav"
        prompt_text = "人家补课补来补去的也就上了个鉴湖，他什么都不补课也能上鉴湖。"
        prompt_lang = "zh"

        if not Path(ref_audio_path).exists():
            d = Dialog('参考音频不存在', f'参考音频文件不存在，请检查路径：{ref_audio_path}', self)
            d.exec()
            return

        self.generate_button.setText("生成中...")
        self.generate_button.setEnabled(False)

        worker = TTSWorker(text, ref_audio_path, prompt_text, prompt_lang)
        worker.signals.finished.connect(self.on_generation_finished)
        worker.signals.errno.connect(self.on_generation_error)
        self.thread_pool.start(worker)

    def on_generation_finished(self, save_path, text):
        InfoBar.success('生成成功', f'音频文件已保存到 {save_path}', parent=self)
        self.generate_button.setText("生成声音")
        self.generate_button.setEnabled(True)

        new_history_item = {'text': text, 'filename': save_path}
        self.history.insert(0, new_history_item)  # 插入到最前面
        self.save_history()

        # 刷新表格显示
        self.history_table.setRowCount(0)
        for item in self.history:
            self.add_history_item_to_table(item['text'], item['filename'])

    def on_generation_error(self, _, error_message):
        InfoBar.error('生成失败', error_message, parent=self)
        self.generate_button.setText("生成声音")
        self.generate_button.setEnabled(True)

    def show_context_menu(self, pos):
        row = self.history_table.rowAt(pos.y())
        if row < 0:
            return

        menu = RoundMenu(parent=self)
        delete_action = Action(FIF.DELETE, '删除此条记录')
        menu.addAction(delete_action)

        delete_action.triggered.connect(lambda: self.delete_history_item(row))
        menu.exec(QCursor.pos())

    def delete_history_item(self, row):
        self.history_table.removeRow(row)
        del self.history[row]
        self.save_history()
        InfoBar.success('已删除', '该条历史记录已删除。', parent=self)


class APIVoiceWorker(QRunnable):
    """API语音合成工作线程 - 使用轮询机制，支持队列满自动切换密钥"""

    # 查询API URL
    QUERY_URL = "https://api.bizyair.cn/w/v1/webapp/task/openapi/query"
    CREATE_URL = "https://api.bizyair.cn/w/v1/webapp/task/openapi/create"

    # 超时设置（秒）
    SUBMIT_TIMEOUT = 300  # 提交任务超时：5分钟（音频base64可能很大）
    QUERY_TIMEOUT = 60    # 查询任务超时：1分钟
    DOWNLOAD_TIMEOUT = 180  # 下载音频超时：3分钟

    # 队列满错误码
    QUEUE_FULL_CODE = 30039

    def __init__(self, api_keys_list, voice_color, target_text, voice_colors_data, task_row):
        """
        初始化工作线程
        :param api_keys_list: API密钥列表（支持自动切换）
        :param voice_color: 音色名称
        :param target_text: 目标文本
        :param voice_colors_data: 音色数据
        :param task_row: 任务在表格中的行号
        """
        super().__init__()
        self.api_keys_list = api_keys_list  # 完整的API密钥列表
        self.current_key_index = 0  # 当前使用的密钥索引
        self.voice_color = voice_color
        self.target_text = target_text
        self.voice_colors_data = voice_colors_data
        self.task_row = task_row  # 任务在表格中的行号
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            import time

            # 查找选中的音色数据
            selected_voice = None
            for voice in self.voice_colors_data:
                if voice['title'] == self.voice_color:
                    selected_voice = voice
                    break

            if not selected_voice:
                raise Exception(f"未找到音色: {self.voice_color}")

            # 获取音频URL（直接使用slicer_opt.json中的URL）
            audio_url = selected_voice['filename']

            logging.info(f"[+]音频URL: {audio_url}")

            if not audio_url:
                raise Exception(f"音频URL为空")

            # 直接使用音频URL，不需要base64编码
            data = {
                "web_app_id": 45578,
                "suppress_preview_output": False,
                "input_values": {
                    "40:FB_Qwen3TTSVoiceClone.target_text": self.target_text,
                    "24:LoadAudio.audio": audio_url,  # 直接使用URL
                    "40:FB_Qwen3TTSVoiceClone.ref_text": selected_voice['content']
                }
            }

            logging.info(f"[+]目标文本: {self.target_text[:50]}...")
            logging.info(f"[+]参考文本: {selected_voice['content'][:50]}...")

            # 第一步：提交任务（支持自动切换密钥重试）
            request_id = None
            headers = None
            max_retries = len(self.api_keys_list)  # 最多重试所有密钥数量次

            for retry_count in range(max_retries):
                # 获取当前密钥
                api_key = self.api_keys_list[self.current_key_index]
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }

                logging.info(f"[+]尝试提交任务 (密钥 {self.current_key_index + 1}/{len(self.api_keys_list)})")

                # 发送请求
                self.signals.progress.emit(self.task_row, "提交", f"正在提交任务... (密钥 {self.current_key_index + 1}/{len(self.api_keys_list)})")
                response = requests.post(self.CREATE_URL, headers=headers, json=data, timeout=self.SUBMIT_TIMEOUT)
                result = response.json()

                logging.info(f"[+]API提交响应: {result}")

                # 检查是否队列满
                if result.get('code') == self.QUEUE_FULL_CODE:
                    # 队列满，切换到下一个密钥重试
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys_list)
                    retry_msg = result.get('message', '队列已满')
                    logging.info(f"[+]队列满，切换密钥重试: {retry_msg}")
                    self.signals.progress.emit(self.task_row, "队列满", f"队列已满，切换密钥 ({retry_count + 1}/{max_retries})")
                    time.sleep(1)  # 短暂等待后重试
                    continue

                # 检查是否成功获得 request_id
                if result.get('request_id'):
                    request_id = result['request_id']
                    logging.info(f"[+]任务ID: {request_id}")
                    self.signals.progress.emit(self.task_row, "提交", "任务提交成功")
                    break  # 成功提交，退出重试循环
                else:
                    # 其他错误，不再重试
                    error_msg = result.get('message', 'API返回失败')
                    raise Exception(f"API提交失败: {error_msg}")

            # 如果所有密钥都尝试过仍未成功
            if not request_id:
                raise Exception(f"所有API密钥队列已满或无法使用，请稍后再试")

            # 第二步：等待30秒后开始轮询
            self.signals.progress.emit(self.task_row, "等待", "等待云端处理... (30秒)")
            for i in range(30, 0, -5):
                time.sleep(5)
                self.signals.progress.emit(self.task_row, "等待", f"等待处理中... ({i}秒)")

            # 第三步：轮询查询结果
            max_polls = 24  # 最多轮询24次 (2分钟)
            poll_interval = 5  # 每5秒查询一次

            for poll_count in range(max_polls):
                time.sleep(poll_interval)

                query_data = {"request_id": request_id}
                query_response = requests.post(self.QUERY_URL, headers=headers, json=query_data, timeout=self.QUERY_TIMEOUT)
                query_result = query_response.json()

                logging.info(f"[+]轮询查询 {poll_count + 1}: {query_result.get('status', 'Unknown')}")

                remaining_time = (max_polls - poll_count) * poll_interval
                self.signals.progress.emit(self.task_row, "处理中", f"生成中... ({remaining_time}秒)")

                if query_result.get('status') == 'Success':
                    # 任务完成，获取音频URL
                    if query_result.get('outputs'):
                        audio_url = query_result['outputs'][0]['object_url']

                        # 下载音频文件
                        self.signals.progress.emit(self.task_row, "下载", "正在下载音频文件...")
                        download_response = requests.get(audio_url, timeout=self.DOWNLOAD_TIMEOUT)
                        if download_response.status_code == 200:
                            # 保存到output目录
                            output_dir = Path("output")
                            output_dir.mkdir(exist_ok=True)

                            # 使用合成文本的前20个字符作为文件名
                            safe_filename = "".join(c for c in self.target_text[:20] if c.isalnum() or c in (' ', '-', '_')).strip()
                            if not safe_filename:
                                safe_filename = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                            filename = f"{safe_filename}.mp3"
                            save_path = output_dir / filename

                            with open(save_path, 'wb') as f:
                                f.write(download_response.content)

                            logging.info(f"[+]音频文件已保存到: {save_path}")
                            # 返回 (本地路径, URL)
                            self.signals.finished.emit(str(save_path), audio_url)
                            return
                        else:
                            raise Exception(f"下载音频失败: {download_response.status_code}")
                    else:
                        raise Exception("API返回成功但无音频输出")
                elif query_result.get('status') == 'Failed':
                    error_msg = query_result.get('message', '任务执行失败')
                    raise Exception(f"API任务失败: {error_msg}")
                # 其他状态继续轮询

            raise Exception("轮询超时，任务未在预期时间内完成")

        except requests.exceptions.Timeout as e:
            error_msg = f"请求超时，请检查网络连接或稍后重试 (超时限制: {self.SUBMIT_TIMEOUT}秒)"
            logging.error(error_msg)
            self.signals.errno.emit("TIMEOUT_ERROR", error_msg)
        except requests.exceptions.RequestException as e:
            error_msg = f"调用API时网络错误: {e}"
            logging.error(error_msg)
            self.signals.errno.emit("NETWORK_ERROR", error_msg)
        except Exception as e:
            error_msg = f"处理API声音生成时发生错误: {e}"
            logging.error(error_msg)
            self.signals.errno.emit("UNKNOWN_ERROR", error_msg)


class APIVoiceApiWidget(QWidget):
    """API声音生成界面 - 支持密钥文件和批量处理"""

    HISTORY_FILE = Path("api_voice_history.json")
    DEFAULT_KEY_FILE = "/Volumes/BO/AI/custom_nodes/comfyui_bozo/key/siliconflow_API_key.txt"

    def __init__(self):
        super().__init__()
        self.voice_colors_data = []
        self.api_keys = []  # 密钥列表
        self.current_key_index = 0  # 当前使用的密钥索引
        self.history = []
        self.active_tasks = 0  # 活跃任务计数
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(5)  # 支持并发任务
        self.load_voice_colors()
        self.load_api_keys(self.DEFAULT_KEY_FILE)
        self.init_ui()
        self.load_history()  # 需要在 init_ui 之后调用，因为 history_table 在 init_ui 中创建

    def load_voice_colors(self):
        """从slicer_opt.json加载音色数据"""
        config_path = Path("slicer_opt.json")
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.voice_colors_data = json.load(f)
                logging.info(f"[+]加载了 {len(self.voice_colors_data)} 个音色")
            except Exception as e:
                logging.error(f"加载音色数据失败: {e}")
                self.voice_colors_data = []
        else:
            logging.warning(f"音色配置文件不存在: {config_path}")
            self.voice_colors_data = []

    def load_api_keys(self, key_file_path):
        """从密钥文件加载API密钥"""
        try:
            key_path = Path(key_file_path)
            if key_path.exists():
                with open(key_path, 'r', encoding='utf-8') as f:
                    # 读取所有非空行
                    self.api_keys = [line.strip() for line in f.readlines() if line.strip()]
                logging.info(f"[+]加载了 {len(self.api_keys)} 个API密钥")
                self.update_key_status()
                return True
            else:
                logging.warning(f"密钥文件不存在: {key_file_path}")
                self.api_keys = []
                self.update_key_status()
                return False
        except Exception as e:
            logging.error(f"加载密钥文件失败: {e}")
            self.api_keys = []
            self.update_key_status()
            return False

    def get_next_api_key(self):
        """获取下一个API密钥（轮询）"""
        if not self.api_keys:
            return None
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    def update_key_status(self):
        """更新密钥状态显示"""
        if hasattr(self, 'key_status_label'):
            if self.api_keys:
                self.key_status_label.setText(f"密钥: {len(self.api_keys)}个 (当前: 第{self.current_key_index + 1}个)")
            else:
                self.key_status_label.setText("密钥: 未加载")
                self.key_status_label.setStyleSheet("color: red; font-size: 10px;")

    def load_history(self):
        """加载历史记录"""
        if self.HISTORY_FILE.exists():
            try:
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
                for item in self.history:
                    self.add_history_item_to_table(item['text'], item.get('local_path', ''), item.get('audio_url', ''))
            except (IOError, json.JSONDecodeError) as e:
                logging.error(f"加载历史记录失败: {e}")
                self.history = []

    def save_history(self):
        """保存历史记录"""
        try:
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=4)
        except IOError as e:
            logging.error(f"保存历史记录失败: {e}")

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 顶部一行：音色选择 + 密钥文件
        top_layout = QHBoxLayout()

        # 音色选择
        voice_label = BodyLabel("音色:", self)
        voice_label.setFixedWidth(50)
        self.voice_combo = ComboBox(self)
        self.voice_combo.addItems([voice['title'] for voice in self.voice_colors_data])
        self.voice_combo.currentIndexChanged.connect(self.on_voice_changed)
        top_layout.addWidget(voice_label)
        top_layout.addWidget(self.voice_combo)

        # 音色描述
        self.voice_desc_label = BodyLabel("", self)
        self.voice_desc_label.setStyleSheet("color: gray; font-size: 10px;")
        self.voice_desc_label.setMaximumWidth(200)
        top_layout.addWidget(self.voice_desc_label)

        top_layout.addSpacing(20)

        # 密钥文件路径
        key_file_label = BodyLabel("密钥文件:", self)
        self.key_file_input = LineEdit(self)
        self.key_file_input.setText(self.DEFAULT_KEY_FILE)
        self.key_file_input.setReadOnly(True)
        key_browse_button = PushButton("浏览", self)
        key_browse_button.setFixedWidth(60)
        key_browse_button.clicked.connect(self.browse_key_file)
        top_layout.addWidget(key_file_label)
        top_layout.addWidget(self.key_file_input)
        top_layout.addWidget(key_browse_button)

        # 密钥状态
        self.key_status_label = BodyLabel("", self)
        self.key_status_label.setStyleSheet("color: #0078d4; font-size: 10px;")
        top_layout.addWidget(self.key_status_label)

        layout.addLayout(top_layout)

        # 多行文本输入框（顶部）
        self.text_input = TextEdit(self)
        self.text_input.setPlaceholderText("在此输入需要合成语音的文本...")
        self.text_input.setFixedHeight(100)
        layout.addWidget(self.text_input)

        # 状态显示标签
        self.status_label = BodyLabel("", self)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #0078d4; font-size: 12px;")
        layout.addWidget(self.status_label)

        # 任务记录表格（任务模式）
        task_label = BodyLabel("任务记录:", self)
        layout.addWidget(task_label)

        self.history_table = TableWidget(self)
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(['文本', '状态', '文件', '操作'])
        self.history_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.show_context_menu)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.setWordWrap(True)
        self.history_table.setMaximumHeight(200)
        layout.addWidget(self.history_table)

        # 声音生成按钮（支持多次点击）
        self.generate_button = PushButton("生成声音", self)
        self.generate_button.clicked.connect(self.generate_voice)
        layout.addWidget(self.generate_button)

        # 初始化音色描述和密钥状态
        if self.voice_colors_data:
            self.on_voice_changed(0)

    def browse_key_file(self):
        """浏览密钥文件"""
        file, _ = QFileDialog.getOpenFileName(self, "选择密钥文件", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if file:
            self.key_file_input.setText(file)
            self.load_api_keys(file)

    def on_voice_changed(self, index):
        """音色选择改变时的处理"""
        if 0 <= index < len(self.voice_colors_data):
            voice = self.voice_colors_data[index]
            ref_text = voice['content']
            if len(ref_text) > 25:
                ref_text = ref_text[:25] + "..."
            self.voice_desc_label.setText(f"参考: {ref_text}")

    def add_history_item_to_table(self, text, local_path, audio_url, status="已完成"):
        """添加历史记录到表格"""
        row_count = self.history_table.rowCount()
        self.history_table.insertRow(row_count)

        # 文本
        text_item = QTableWidgetItem(text)
        text_item.setFlags(text_item.flags() & ~Qt.ItemIsEditable)
        self.history_table.setItem(row_count, 0, text_item)

        # 状态
        status_item = QTableWidgetItem(status)
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        if status == "已完成":
            status_item.setForeground(QColor("green"))
        elif status == "处理中":
            status_item.setForeground(QColor("orange"))
        elif status == "错误":
            status_item.setForeground(QColor("red"))
        self.history_table.setItem(row_count, 1, status_item)

        # 文件名
        file_name = os.path.basename(local_path) if local_path else audio_url
        file_item = QTableWidgetItem(file_name)
        file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
        file_item.setData(Qt.UserRole, {'local_path': local_path, 'audio_url': audio_url})
        self.history_table.setItem(row_count, 2, file_item)

        # 操作按钮
        play_button = PushButton(FIF.PLAY, "播放")
        play_button.clicked.connect(lambda _, r=row_count: self.play_audio(r))
        self.history_table.setCellWidget(row_count, 3, play_button)
        self.history_table.resizeRowsToContents()

    def update_task_status(self, row, status):
        """更新任务状态"""
        if row < self.history_table.rowCount():
            status_item = self.history_table.item(row, 1)
            status_item.setText(status)
            if status == "已完成":
                status_item.setForeground(QColor("green"))
            elif status == "处理中":
                status_item.setForeground(QColor("orange"))
            elif status == "错误":
                status_item.setForeground(QColor("red"))

    def play_audio(self, row):
        """播放音频"""
        item = self.history_table.item(row, 2)
        data = item.data(Qt.UserRole)
        local_path = data.get('local_path', '')

        if local_path and os.path.exists(local_path):
            try:
                if platform.system() == "Windows":
                    os.startfile(local_path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", local_path])
                else:
                    subprocess.Popen(["xdg-open", local_path])
            except Exception as e:
                InfoBar.error('播放失败', f'无法播放文件: {e}', parent=self)
        elif data.get('audio_url'):
            try:
                webbrowser.open(data['audio_url'])
            except Exception as e:
                InfoBar.error('打开失败', f'无法打开URL: {e}', parent=self)
        else:
            InfoBar.warning('文件不存在', '音频文件不存在。', parent=self)

    def show_context_menu(self, pos):
        """显示右键菜单"""
        row = self.history_table.rowAt(pos.y())
        if row < 0:
            return

        menu = RoundMenu(parent=self)
        play_action = Action(FIF.PLAY, '播放音频')
        open_file_action = Action(FIF.FOLDER, '打开文件')
        open_url_action = Action(FIF.LINK, '打开URL')
        delete_action = Action(FIF.DELETE, '删除此条记录')

        menu.addActions([play_action, open_file_action, open_url_action, delete_action])

        play_action.triggered.connect(lambda: self.play_audio(row))
        open_file_action.triggered.connect(lambda: self.open_file(row))
        open_url_action.triggered.connect(lambda: self.open_url(row))
        delete_action.triggered.connect(lambda: self.delete_history_item(row))

        menu.exec(QCursor.pos())

    def open_file(self, row):
        """打开文件所在目录"""
        item = self.history_table.item(row, 2)
        data = item.data(Qt.UserRole)
        local_path = data.get('local_path', '')

        if local_path and os.path.exists(local_path):
            try:
                directory = os.path.dirname(local_path)
                if platform.system() == "Windows":
                    os.startfile(directory)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", directory])
                else:
                    subprocess.Popen(["xdg-open", directory])
            except Exception as e:
                InfoBar.error('打开失败', f'无法打开目录: {e}', parent=self)
        else:
            InfoBar.warning('文件不存在', '本地文件不存在。', parent=self)

    def open_url(self, row):
        """打开音频URL"""
        item = self.history_table.item(row, 2)
        data = item.data(Qt.UserRole)
        audio_url = data.get('audio_url', '')

        if audio_url:
            try:
                webbrowser.open(audio_url)
            except Exception as e:
                InfoBar.error('打开失败', f'无法打开URL: {e}', parent=self)
        else:
            InfoBar.warning('URL不存在', '没有保存的URL。', parent=self)

    def delete_history_item(self, row):
        """删除历史记录"""
        self.history_table.removeRow(row)
        if row < len(self.history):
            del self.history[row]
            self.save_history()
        InfoBar.success('已删除', '该条历史记录已删除。', parent=self)

    def generate_voice(self):
        """生成声音 - 支持批量处理"""
        text = self.text_input.toPlainText().strip()
        if not text:
            InfoBar.warning('内容为空', '请输入需要合成的文本。', parent=self)
            return

        # 检查密钥列表
        if not self.api_keys:
            InfoBar.warning('密钥为空', '请先加载密钥文件。', parent=self)
            return

        if not self.voice_colors_data:
            InfoBar.warning('音色数据为空', '未找到音色配置数据。', parent=self)
            return

        voice_color = self.voice_combo.currentText()

        # 添加到历史记录（初始状态为处理中）
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_task = {
            'text': text,
            'local_path': '',
            'audio_url': '',
            'timestamp': timestamp,
            'status': '处理中'
        }
        self.history.insert(0, new_task)
        self.add_history_item_to_table(text, '', '', '处理中')
        task_row = 0  # 新任务总是在第一行

        # 增加活跃任务计数
        self.active_tasks += 1
        self.update_status_display()

        # 启动工作线程（传递完整的API密钥列表和任务行号）
        worker = APIVoiceWorker(self.api_keys, voice_color, text, self.voice_colors_data, task_row)
        worker.signals.progress.connect(self.on_task_progress)
        worker.signals.finished.connect(lambda lp, au: self.on_task_finished(task_row, lp, au))
        worker.signals.errno.connect(lambda err: self.on_task_error(task_row, err))
        self.thread_pool.start(worker)

        # 更新密钥状态显示
        self.update_key_status()

    def on_task_progress(self, row, status, message):
        """任务进度更新 - 支持每个任务的独立倒计时"""
        # 更新表格中对应任务行的状态
        if row < self.history_table.rowCount():
            # 更新状态列
            status_item = self.history_table.item(row, 1)
            if status_item:
                status_item.setText(message)
                # 根据状态设置颜色
                if status == "准备":
                    status_item.setForeground(QColor("#666666"))
                elif status == "编码":
                    status_item.setForeground(QColor("#0078d4"))
                elif status == "提交":
                    status_item.setForeground(QColor("#0066cc"))
                elif status == "队列满":
                    status_item.setForeground(QColor("#ff0066"))  # 红色表示队列满
                elif status == "等待":
                    status_item.setForeground(QColor("#ff9900"))
                elif status == "处理中":
                    status_item.setForeground(QColor("#ff6600"))
                elif status == "下载":
                    status_item.setForeground(QColor("#009933"))

        # 更新全局状态标签
        if self.active_tasks > 0:
            self.status_label.setText(f"正在处理 {self.active_tasks} 个任务...")

    def on_task_finished(self, row, local_path, audio_url):
        """任务完成回调"""
        # 减少活跃任务计数
        self.active_tasks -= 1

        # 更新历史记录
        if row < len(self.history):
            self.history[row]['local_path'] = local_path
            self.history[row]['audio_url'] = audio_url
            self.history[row]['status'] = '已完成'
            self.save_history()

            # 更新表格
            self.update_task_status(row, '已完成')

            # 更新文件列
            file_item = self.history_table.item(row, 2)
            file_name = os.path.basename(local_path)
            file_item.setText(file_name)
            file_item.setData(Qt.UserRole, {'local_path': local_path, 'audio_url': audio_url})

        InfoBar.success('生成成功', f'音频文件已保存', parent=self)
        self.update_status_display()

    def on_task_error(self, row, error_message):
        """任务错误回调"""
        # 减少活跃任务计数
        self.active_tasks -= 1

        # 更新历史记录
        if row < len(self.history):
            self.history[row]['status'] = '错误'
            self.history[row]['error'] = error_message
            self.save_history()
            self.update_task_status(row, '错误')

        InfoBar.error('生成失败', error_message, parent=self)
        self.update_status_display()

    def update_status_display(self):
        """更新状态显示"""
        if self.active_tasks > 0:
            self.status_label.setText(f"正在处理 {self.active_tasks} 个任务...")
        else:
            self.status_label.setText("")


class SrtOptimizerWidget(QWidget):
    """SRT优化界面"""
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1) # 只处理单个任务

    def init_ui(self):
        layout = QVBoxLayout(self)

        # SRT源文件选择
        srt_path_layout = QHBoxLayout()
        srt_path_label = BodyLabel("SRT源文件:", self)
        srt_path_label.setFixedWidth(80)
        self.srt_path_input = LineEdit(self)
        self.srt_path_input.setPlaceholderText("选择或拖拽SRT文件到这里")
        self.srt_path_input.setReadOnly(True)
        self.srt_path_button = PushButton("选择文件", self)
        self.srt_path_button.clicked.connect(self.select_srt_file)
        srt_path_layout.addWidget(srt_path_label)
        srt_path_layout.addWidget(self.srt_path_input)
        srt_path_layout.addWidget(self.srt_path_button)
        layout.addLayout(srt_path_layout)

        # 保存路径选择
        save_path_layout = QHBoxLayout()
        save_path_label = BodyLabel("保存路径:", self)
        save_path_label.setFixedWidth(80)
        self.save_path_input = LineEdit(self)
        self.save_path_input.setPlaceholderText("选择保存路径 (默认为源文件同目录)")
        self.save_path_input.setReadOnly(True)
        self.save_path_button = PushButton("选择路径", self)
        self.save_path_button.clicked.connect(self.select_save_path)
        save_path_layout.addWidget(save_path_label)
        save_path_layout.addWidget(self.save_path_input)
        save_path_layout.addWidget(self.save_path_button)
        layout.addLayout(save_path_layout)

        # 状态显示区域
        self.status_label = BodyLabel("请选择文件开始处理", self)
        self.status_label.setAlignment(Qt.AlignCenter)
        font = self.status_label.font()
        font.setPointSize(12)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label)
        
        # 占位符，让按钮在底部
        layout.addStretch()

        # 处理按钮
        self.process_button = PushButton("开始处理", self)
        self.process_button.clicked.connect(self.process_srt)
        self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)

        self.setAcceptDrops(True)

    def select_srt_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择SRT文件", "", "SRT Files (*.srt)")
        if file:
            self.srt_path_input.setText(file)
            default_save_path = file.rsplit('.', 1)[0] + "_merged.srt"
            self.save_path_input.setText(default_save_path)
            self.update_process_button_state()

    def select_save_path(self):
        srt_path = self.srt_path_input.text()
        if not srt_path:
            # 如果没有源文件，则在用户主目录打开
            default_dir = str(Path.home())
        else:
            # 否则在源文件目录打开
            default_dir = os.path.dirname(srt_path)
            
        file, _ = QFileDialog.getSaveFileName(self, "选择保存路径", default_dir, "SRT Files (*.srt)")
        if file:
            self.save_path_input.setText(file)
            self.update_process_button_state()

    def process_srt(self):
        srt_path = self.srt_path_input.text()
        save_path = self.save_path_input.text()

        if not srt_path or not save_path:
            InfoBar.warning("提示", "请先选择SRT源文件和保存路径", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        self.process_button.setEnabled(False)
        self.status_label.setText("处理中...")

        worker = SrtOptimizerWorker(srt_path, save_path)
        worker.signals.finished.connect(self.on_processing_finished)
        worker.signals.errno.connect(self.on_processing_error)
        self.thread_pool.start(worker)

    def on_processing_finished(self, _, message):
        self.status_label.setText(message)
        InfoBar.success("成功", message, parent=self, position=InfoBarPosition.TOP, duration=3000)
        self.update_process_button_state()

    def on_processing_error(self, _, error_message):
        self.status_label.setText(f"处理失败")
        w = MessageBox("处理失败", error_message, self)
        w.exec()
        self.update_process_button_state()

    def update_process_button_state(self):
        srt_path = self.srt_path_input.text()
        save_path = self.save_path_input.text()
        is_processing = self.status_label.text() == "处理中..."
        self.process_button.setEnabled(bool(srt_path and save_path) and not is_processing)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].toLocalFile().lower().endswith('.srt'):
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        self.srt_path_input.setText(file_path)
        default_save_path = file_path.rsplit('.', 1)[0] + "_merged.srt"
        self.save_path_input.setText(default_save_path)
        self.update_process_button_state()


class MergeMediaWorker(QRunnable):
    """音视频合并工作线程"""
    def __init__(self, files, output_path, media_type):
        super().__init__()
        self.files = files
        self.output_path = output_path
        self.media_type = media_type  # 'audio' or 'video'
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            if not self.files:
                raise Exception("没有选择文件")

            # 创建输出目录
            output_dir = os.path.dirname(self.output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            if self.media_type == 'audio':
                # 音频合并：使用concat协议
                if len(self.files) == 1:
                    # 只有一个文件，直接复制
                    import shutil
                    shutil.copy2(self.files[0], self.output_path)
                    logging.info(f"音频合并完成：{self.output_path}")
                else:
                    # 创建临时列表文件
                    list_file = os.path.join(output_dir, 'filelist.txt')
                    with open(list_file, 'w', encoding='utf-8') as f:
                        for file in self.files:
                            # 使用引号处理文件名中的空格和特殊字符
                            f.write(f"file '{file}'\n")

                    # 使用ffmpeg合并音频
                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', list_file,
                        '-c', 'copy',
                        '-y',
                        self.output_path
                    ]

                    result = subprocess.run(cmd, capture_output=True, check=True,
                                          encoding='utf-8', errors='replace')

                    # 删除临时文件
                    if os.path.exists(list_file):
                        os.remove(list_file)

                    if result.returncode == 0 and os.path.exists(self.output_path):
                        logging.info(f"音频合并完成：{self.output_path}")
                    else:
                        raise Exception("音频合并失败")

            elif self.media_type == 'video':
                # 视频合并：使用concat协议
                if len(self.files) == 1:
                    # 只有一个文件，直接复制
                    import shutil
                    shutil.copy2(self.files[0], self.output_path)
                    logging.info(f"视频合并完成：{self.output_path}")
                else:
                    # 创建临时列表文件
                    list_file = os.path.join(output_dir, 'filelist.txt')
                    with open(list_file, 'w', encoding='utf-8') as f:
                        for file in self.files:
                            # 使用引号处理文件名中的空格和特殊字符
                            f.write(f"file '{file}'\n")

                    # 使用ffmpeg合并视频（先尝试concat，失败则重新编码）
                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', list_file,
                        '-c', 'copy',
                        '-y',
                        self.output_path
                    ]

                    result = subprocess.run(cmd, capture_output=True,
                                          encoding='utf-8', errors='replace')

                    # 删除临时文件
                    if os.path.exists(list_file):
                        os.remove(list_file)

                    if result.returncode != 0 or not os.path.exists(self.output_path):
                        # 如果concat失败，使用重新编码方式
                        logging.info("concat方式失败，尝试重新编码合并")
                        list_file = os.path.join(output_dir, 'filelist.txt')
                        with open(list_file, 'w', encoding='utf-8') as f:
                            for file in self.files:
                                f.write(f"file '{file}'\n")

                        cmd = [
                            'ffmpeg',
                            '-f', 'concat',
                            '-safe', '0',
                            '-i', list_file,
                            '-c:v', 'libx264',
                            '-c:a', 'aac',
                            '-y',
                            self.output_path
                        ]

                        result = subprocess.run(cmd, capture_output=True, check=True,
                                              encoding='utf-8', errors='replace')
                        os.remove(list_file)

                    if result.returncode == 0 and os.path.exists(self.output_path):
                        logging.info(f"视频合并完成：{self.output_path}")
                    else:
                        raise Exception("视频合并失败")

            self.signals.finished.emit(self.output_path, f"合并完成，文件已保存到：{self.output_path}")

        except Exception as e:
            logging.error(f"合并失败：{str(e)}")
            self.signals.errno.emit(self.output_path, str(e))


class MergeMediaWidget(QWidget):
    """音视频合并界面"""

    def __init__(self):
        super().__init__()
        self.files = []
        self.thread_pool = QThreadPool()
        self.processing = False
        self.media_type = 'audio'  # 默认音频模式
        
        # JSON配置文件路径
        self.config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, 'merge_media_config.json')
        
        # 先初始化UI
        self.init_ui()
        self.setAcceptDrops(True)
        
        # UI初始化完成后再加载配置
        self.load_config()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # 选项卡切换（顶部）
        self.segmented = SegmentedWidget(self)
        self.segmented.addItem(routeKey='audio', text='音频合并', onClick=lambda: self.switch_mode('audio'))
        self.segmented.addItem(routeKey='video', text='视频合并', onClick=lambda: self.switch_mode('video'))
        self.segmented.setCurrentItem('audio')
        layout.addWidget(self.segmented)

        # 文件列表标签
        list_label = BodyLabel("源文件列表（可拖拽文件到此处添加）", self)
        list_label.setFont(QFont("Segoe UI", 14))
        layout.addWidget(list_label)

        # 文件表格（自适应高度）
        self.table = TableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['文件名', '序号', '操作'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(TableWidget.SelectRows)
        # 禁用内部拖拽，改用按钮上下移
        self.table.setDragDropMode(TableWidget.DropOnly)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        # 设置拖拽行为
        self.table.dragEnterEvent = self.table_drag_enter_event
        self.table.dropEvent = self.table_drop_event
        # 设置表格可以自适应高度
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.table)

        # 占位符（让上面的表格可以自适应高度）
        layout.addStretch()

        # 操作按钮区域
        button_layout = QHBoxLayout()

        add_button = PushButton(FIF.ADD, "添加文件", self)
        add_button.clicked.connect(self.select_files)
        button_layout.addWidget(add_button)

        up_button = PushButton(FIF.UP, "上移", self)
        up_button.clicked.connect(self.move_up)
        button_layout.addWidget(up_button)

        down_button = PushButton(FIF.DOWN, "下移", self)
        down_button.clicked.connect(self.move_down)
        button_layout.addWidget(down_button)

        remove_button = PushButton(FIF.DELETE, "移除选中", self)
        remove_button.clicked.connect(self.remove_selected)
        button_layout.addWidget(remove_button)

        clear_button = PushButton(FIF.CANCEL, "清空列表", self)
        clear_button.clicked.connect(self.clear_files)
        button_layout.addWidget(clear_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # 输出设置区域
        output_layout = QHBoxLayout()

        output_label = BodyLabel("输出目录：", self)
        output_label.setFixedWidth(80)
        self.output_input = LineEdit(self)
        self.output_input.setPlaceholderText("默认保存到 output 目录")
        self.output_input.setText(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output'))
        self.output_input.setReadOnly(True)
        output_browse_button = PushButton("浏览", self)
        output_browse_button.clicked.connect(self.browse_output)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(output_browse_button)
        layout.addLayout(output_layout)

        # 日志区域
        log_label = BodyLabel("处理日志：", self)
        log_label.setFont(QFont("Segoe UI", 12))
        layout.addWidget(log_label)

        self.log_text = TextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("日志将显示在这里...")
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        # 开始合并按钮（最下方）
        self.merge_button = PushButton(FIF.SYNC, "开始合并", self)
        self.merge_button.setMinimumHeight(45)
        self.merge_button.clicked.connect(self.start_merge)
        self.merge_button.setEnabled(False)
        layout.addWidget(self.merge_button)

    def switch_mode(self, mode):
        """切换音频/视频模式"""
        self.media_type = mode
        # 清空当前列表
        self.files.clear()
        self.table.setRowCount(0)
        self.update_merge_button_state()
        self.add_log(f"切换到 {'音频' if mode == 'audio' else '视频'} 合并模式")
        # 切换模式后重新加载对应模式的配置
        self.load_config()
    
    def move_up(self):
        """上移选中的文件"""
        current_row = self.table.currentRow()
        if current_row > 0:
            # 交换文件
            self.files[current_row], self.files[current_row - 1] = self.files[current_row - 1], self.files[current_row]
            # 重建表格
            self.refresh_table_from_files()
            # 保存配置
            self.save_config()
            # 重新选中
            self.table.selectRow(current_row - 1)
            self.add_log(f"上移：{os.path.basename(self.files[current_row - 1])}")
    
    def move_down(self):
        """下移选中的文件"""
        current_row = self.table.currentRow()
        if current_row >= 0 and current_row < len(self.files) - 1:
            # 交换文件
            self.files[current_row], self.files[current_row + 1] = self.files[current_row + 1], self.files[current_row]
            # 重建表格
            self.refresh_table_from_files()
            # 保存配置
            self.save_config()
            # 重新选中
            self.table.selectRow(current_row + 1)
            self.add_log(f"下移：{os.path.basename(self.files[current_row + 1])}")
    
    def load_config(self):
        """从JSON文件加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                # 根据当前模式加载对应的文件列表
                mode_key = 'audio' if self.media_type == 'audio' else 'video'
                if mode_key in config and isinstance(config[mode_key], list):
                    # 只保留仍然存在的文件
                    valid_files = []
                    for item in config[mode_key]:
                        if os.path.exists(item['path']):
                            valid_files.append(item['path'])
                    
                    self.files = valid_files
                    
                    # 重建表格
                    self.refresh_table_from_files()
                    
                    if valid_files:
                        self.add_log(f"已加载 {len(valid_files)} 个文件")
                else:
                    self.files = []
                    self.table.setRowCount(0)
        except Exception as e:
            logging.error(f"加载配置文件失败: {str(e)}")
            self.files = []
            self.table.setRowCount(0)
    
    def save_config(self):
        """保存配置到JSON文件"""
        try:
            config = {}
            
            # 保存音频文件列表
            audio_files = []
            if self.media_type == 'audio':
                for index, file_path in enumerate(self.files):
                    audio_files.append({
                        'path': file_path,
                        'sequence': index + 1
                    })
            config['audio'] = audio_files
            
            # 保存视频文件列表
            video_files = []
            if self.media_type == 'video':
                for index, file_path in enumerate(self.files):
                    video_files.append({
                        'path': file_path,
                        'sequence': index + 1
                    })
            config['video'] = video_files
            
            # 写入JSON文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.error(f"保存配置文件失败: {str(e)}")
    
    def refresh_table_from_files(self):
        """从files列表重建表格"""
        # 清空表格
        self.table.setRowCount(0)
        
        # 重新填充表格
        for index, file_path in enumerate(self.files):
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # 文件名
            name_item = QTableWidgetItem(os.path.basename(file_path))
            name_item.setData(Qt.UserRole, file_path)
            self.table.setItem(row, 0, name_item)
            
            # 序号
            seq_item = QTableWidgetItem(str(index + 1))
            seq_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, seq_item)
            
            # 操作按钮
            op_button = PushButton(FIF.DELETE, "删除", self)
            op_button.clicked.connect(lambda checked, r=row: self.remove_row(r))
            self.table.setCellWidget(row, 2, op_button)

    def select_files(self):
        """选择文件对话框"""
        if self.media_type == 'audio':
            files, _ = QFileDialog.getOpenFileNames(self, "选择音频文件", "",
                                                    "音频文件 (*.mp3 *.wav *.ogg *.flac *.aac *.m4a)")
        else:
            files, _ = QFileDialog.getOpenFileNames(self, "选择视频文件", "",
                                                    "视频文件 (*.mp4 *.avi *.mov *.mkv *.ts *.flv)")

        for file in files:
            self.add_file(file)

    def add_file(self, file_path):
        """添加文件到列表"""
        if file_path in self.files:
            InfoBar.warning("提示", f"文件 {os.path.basename(file_path)} 已存在", parent=self,
                          position=InfoBarPosition.TOP, duration=2000)
            return

        self.files.append(file_path)
        row_count = self.table.rowCount()

        # 文件名
        name_item = QTableWidgetItem(os.path.basename(file_path))
        name_item.setData(Qt.UserRole, file_path)

        # 序号
        seq_item = QTableWidgetItem(str(row_count + 1))
        seq_item.setTextAlignment(Qt.AlignCenter)

        # 操作按钮
        op_button = PushButton(FIF.DELETE, "删除", self)
        op_button.clicked.connect(lambda checked, row=row_count: self.remove_row(row))

        self.table.insertRow(row_count)
        self.table.setItem(row_count, 0, name_item)
        self.table.setItem(row_count, 1, seq_item)
        self.table.setCellWidget(row_count, 2, op_button)

        self.update_merge_button_state()
        self.add_log(f"添加文件：{os.path.basename(file_path)}")
        # 保存配置
        self.save_config()

    def remove_row(self, row):
        """删除指定行"""
        if 0 <= row < self.table.rowCount():
            file_path = self.table.item(row, 0).data(Qt.UserRole)
            self.files.remove(file_path)
            self.table.removeRow(row)
            self.refresh_table_from_files()
            self.update_merge_button_state()
            # 保存配置
            self.save_config()

    def remove_selected(self):
        """移除选中的行"""
        selected_rows = set(index.row() for index in self.table.selectedIndexes())
        if not selected_rows:
            InfoBar.warning("提示", "请先选择要移除的文件", parent=self,
                          position=InfoBarPosition.TOP, duration=2000)
            return

        # 从后往前删除，避免索引变化
        for row in sorted(selected_rows, reverse=True):
            file_path = self.table.item(row, 0).data(Qt.UserRole)
            self.files.remove(file_path)
            self.table.removeRow(row)

        self.refresh_table_from_files()
        self.update_merge_button_state()
        # 保存配置
        self.save_config()

    def clear_files(self):
        """清空文件列表"""
        self.files.clear()
        self.table.setRowCount(0)
        self.update_merge_button_state()
        self.add_log("已清空文件列表")
        # 保存配置
        self.save_config()

    def browse_output(self):
        """浏览输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_input.text())
        if dir_path:
            self.output_input.setText(dir_path)

    def update_merge_button_state(self):
        """更新合并按钮状态"""
        has_files = len(self.files) > 0
        self.merge_button.setEnabled(has_files and not self.processing)

    def start_merge(self):
        """开始合并"""
        if not self.files:
            InfoBar.warning("提示", "请先添加文件", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if self.processing:
            return

        # 生成输出文件名（时间戳）
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if self.media_type == 'audio':
            output_file = f"audio_merge_{timestamp}.mp3"
        else:
            output_file = f"video_merge_{timestamp}.mp4"

        output_path = os.path.join(self.output_input.text(), output_file)

        self.processing = True
        self.merge_button.setEnabled(False)
        self.add_log(f"开始合并 {len(self.files)} 个 {'音频' if self.media_type == 'audio' else '视频'} 文件...")

        worker = MergeMediaWorker(self.files, output_path, self.media_type)
        worker.signals.finished.connect(self.on_merge_finished)
        worker.signals.errno.connect(self.on_merge_error)
        self.thread_pool.start(worker)

    def on_merge_finished(self, output_path, message):
        """合并完成回调"""
        self.processing = False
        self.update_merge_button_state()
        self.add_log(f"✅ {message}")
        InfoBar.success("成功", message, parent=self, position=InfoBarPosition.TOP, duration=3000)

        # 打开输出目录
        output_dir = os.path.dirname(output_path)
        try:
            if platform.system() == "Windows":
                os.startfile(output_dir)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", output_dir])
            else:
                subprocess.Popen(["xdg-open", output_dir])
        except Exception as e:
            logging.error(f"无法打开目录：{str(e)}")

    def on_merge_error(self, output_path, error_message):
        """合并错误回调"""
        self.processing = False
        self.update_merge_button_state()
        self.add_log(f"❌ 合并失败：{error_message}")
        InfoBar.error("失败", error_message, parent=self, position=InfoBarPosition.TOP, duration=3000)

    def add_log(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    # 拖拽事件处理
    def dragEnterEvent(self, event):
        """拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """拖拽放置事件"""
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                # 根据当前模式检查文件类型
                if self.media_type == 'audio':
                    audio_exts = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a']
                    if any(file_path.lower().endswith(ext) for ext in audio_exts):
                        self.add_file(file_path)
                    else:
                        InfoBar.warning("提示", "请拖拽音频文件", parent=self,
                                      position=InfoBarPosition.TOP, duration=2000)
                else:
                    video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.ts', '.flv']
                    if any(file_path.lower().endswith(ext) for ext in video_exts):
                        self.add_file(file_path)
                    else:
                        InfoBar.warning("提示", "请拖拽视频文件", parent=self,
                                      position=InfoBarPosition.TOP, duration=2000)

    def table_drag_enter_event(self, event):
        """表格拖拽进入事件"""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super(self.table.__class__, self.table).dragEnterEvent(event)

    def table_drop_event(self, event):
        """表格拖拽放置事件"""
        if event.mimeData().hasUrls():
            # 将文件添加到列表末尾
            self.dropEvent(event)
        else:
            # 处理行拖拽重排
            super(self.table.__class__, self.table).dropEvent(event)


class InfoWidget(QWidget):
    """个人信息界面"""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # GitHub URL 和仓库描述
        GITHUB_URL = "https://github.com/bozoyan/AsrTools"
        REPO_DESCRIPTION = """
    🚀 无需复杂配置：无需 GPU 和繁琐的本地配置，小白也能轻松使用。
    🖥️ 高颜值界面：基于 PyQt5 和 qfluentwidgets，界面美观且用户友好。
    ⚡ 效率超人：多线程并发 + 批量处理，文字转换快如闪电。
    📄 多格式支持：支持生成 .srt 和 .txt 字幕文件，满足不同需求。
        """
        
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)
        # main_layout.setSpacing(50)

        # 标题
        title_label = BodyLabel("  ASRTools v2.1.2", self)
        title_label.setFont(QFont("Segoe UI", 30, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 仓库描述区域
        desc_label = BodyLabel(REPO_DESCRIPTION, self)
        desc_label.setFont(QFont("Segoe UI", 12))
        main_layout.addWidget(desc_label)

        github_button = PushButton("GitHub 仓库 https://github.com/bozoyan/AsrTools ", self)
        github_button.setIcon(FIF.GITHUB)
        github_button.setIconSize(QSize(20, 20))
        github_button.setMinimumHeight(42)
        github_button.clicked.connect(lambda _: webbrowser.open(GITHUB_URL))
        main_layout.addWidget(github_button)


class MainWindow(FluentWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ASR 视频+字幕+音频处理工具')

        # 设置窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # ASR 处理界面
        self.asr_widget = ASRWidget()
        self.asr_widget.setObjectName("main")
        self.addSubInterface(self.asr_widget, FIF.ALBUM, 'ASR 字幕')

        # SRT 优化界面
        self.srt_optimizer_widget = SrtOptimizerWidget()
        self.srt_optimizer_widget.setObjectName("srt_optimizer")
        self.addSubInterface(self.srt_optimizer_widget, FIF.SYNC, 'SRT 优化')

        # 音视频合并界面
        self.merge_media_widget = MergeMediaWidget()
        self.merge_media_widget.setObjectName("merge_media")
        self.addSubInterface(self.merge_media_widget, FIF.CAMERA, '音视频合并')

        # 视频帧提取界面
        self.video_frame_widget = VideoFrameWidget()
        self.video_frame_widget.setObjectName("video_frame")
        self.addSubInterface(self.video_frame_widget, FIF.PHOTO, '视频帧提取')

        # 视频转换界面
        self.video_converter_widget = VideoConverterWidget()
        self.video_converter_widget.setObjectName("video_converter")
        self.addSubInterface(self.video_converter_widget, FIF.MOVIE, '视频转换')

        # 视频转音频界面
        self.video_to_audio_widget = VideoToAudioWidget()
        self.video_to_audio_widget.setObjectName("video_to_audio")
        self.addSubInterface(self.video_to_audio_widget, FIF.MUSIC, '视频转音频')

        # 声音生成界面
        self.voice_api_widget = VoiceApiWidget()
        self.voice_api_widget.setObjectName("voice_api")
        self.addSubInterface(self.voice_api_widget, FIF.SEND, '声音生成')

        # API声音生成界面
        self.api_voice_api_widget = APIVoiceApiWidget()
        self.api_voice_api_widget.setObjectName("api_voice_api")
        self.addSubInterface(self.api_voice_api_widget, FIF.CODE, 'API声音生成')

        # 关于开源 - 移动到导航栏最下方
        self.info_widget = InfoWidget()
        self.info_widget.setObjectName("info")
        self.addSubInterface(self.info_widget, FIF.GITHUB, '关于开源')

        self.navigationInterface.setExpandWidth(200)
        self.resize(800, 600)

        self.update_checker = UpdateCheckerThread(self)
        self.update_checker.msg.connect(self.show_msg)
        self.update_checker.start()

    def show_msg(self, title, content, update_download_url):
        w = MessageBox(title, content, self)
        if w.exec() and update_download_url:
            webbrowser.open(update_download_url)
        if title == "更新":
            sys.exit(0)

def video2audio(input_file: str, output: str = "") -> bool:
    """使用ffmpeg将视频转换为音频"""
    # 创建output目录
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output = str(output)

    cmd = [
        'ffmpeg',
        '-i', input_file,
        '-ac', '1',
        '-f', 'mp3',
        '-af', 'aresample=async=1',
        '-y',
        output
    ]
    result = subprocess.run(cmd, capture_output=True, check=True, encoding='utf-8', errors='replace')

    if result.returncode == 0 and Path(output).is_file():
        return True
    else:
        return False

def start():
    # enable dpi scale
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    # setTheme(Theme.DARK)  # 如果需要深色主题，取消注释此行
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    start()