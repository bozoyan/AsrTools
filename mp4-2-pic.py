import os
import subprocess
import sys

def extract_first_frame(video_path, output_image_path):
    """
    使用ffmpeg提取视频第一帧
    :param video_path: 视频文件路径
    :param output_image_path: 输出图片路径
    """
    try:
        # ffmpeg命令：提取第一帧，不进行编解码（最快方式）
        cmd = [
            'ffmpeg',
            '-i', video_path,          # 输入视频
            '-vframes', '1',           # 只提取1帧
            '-q:v', '2',               # 图片质量（1-31，1质量最高）
            '-y',                      # 覆盖已有文件
            '-ss', '00:00:00',         # 从0秒开始
            output_image_path          # 输出图片路径
        ]
        
        # 执行命令并捕获输出
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        
        if result.returncode == 0:
            print(f"✅ 成功提取: {os.path.basename(video_path)} -> {os.path.basename(output_image_path)}")
        else:
            print(f"❌ 提取失败: {os.path.basename(video_path)}")
            print(f"错误信息: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 处理出错 {os.path.basename(video_path)}: {str(e)}")

def batch_extract_frames(folder_path):
    """
    批量提取文件夹内所有MP4视频的第一帧
    :param folder_path: 视频文件夹路径
    """
    # 检查文件夹是否存在
    if not os.path.exists(folder_path):
        print(f"❌ 文件夹不存在: {folder_path}")
        return
    
    # 遍历文件夹内所有文件
    for filename in os.listdir(folder_path):
        # 只处理MP4文件（不区分大小写）
        if filename.lower().endswith('.mp4'):
            # 构建视频完整路径
            video_full_path = os.path.join(folder_path, filename)
            
            # 构建输出图片路径（同名，格式为jpg）
            image_filename = os.path.splitext(filename)[0] + '.jpg'
            image_full_path = os.path.join(folder_path, image_filename)
            
            # 提取第一帧
            extract_first_frame(video_full_path, image_full_path)

if __name__ == "__main__":
    # 目标文件夹路径
    target_folder = "/Volumes/MAC/客户文件夹/普罗心圈/VOD"
    
    # 检查ffmpeg是否安装
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("❌ 未找到ffmpeg，请先安装ffmpeg！")
        print("安装方法（Mac）: brew install ffmpeg")
        sys.exit(1)
    
    # 开始批量提取
    print(f"📁 开始处理文件夹: {target_folder}")
    print("="*50)
    batch_extract_frames(target_folder)
    print("="*50)
    print("✅ 批量处理完成！")
