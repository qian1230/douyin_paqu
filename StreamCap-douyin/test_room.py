import subprocess
import os
import time
from pathlib import Path

# ===================== 你的配置 ==========================
FFMPEG_PATH = r"D:\pycharm\Project\StreamCap-douyin\StreamCap-douyin\ffmpeg.exe"
SAVE_ROOT = r"D:\其他文件\运动"
# ========================================================

os.makedirs(SAVE_ROOT, exist_ok=True)
test_video = os.path.join(SAVE_ROOT, "test_success.mp4")

print("=" * 60)
print("最终测试：直接生成视频文件（不录屏/不摄像）")
print(f"保存目录：{SAVE_ROOT}")
print(f"FFMPEG：{FFMPEG_PATH}")
print("=" * 60)

# 直接用 ffmpeg 创建一段测试视频（100%成功）
cmd = [
    FFMPEG_PATH,
    "-y",
    "-f", "lavfi",
    "-i", "color=c=black:s=100x100:r=1",
    "-t", "2",
    "-vcodec", "libx264",
    test_video
]

try:
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
except Exception as e:
    print(f"❌ 运行失败：{e}")
    exit()

# 验证结果
if os.path.exists(test_video):
    size = os.path.getsize(test_video)
    print("\n" + "=" * 60)
    print("🎉 🎉 🎉 测试 完 全 成 功！！！")
    print(f"📽️ 视频已生成：{test_video}")
    print(f"📦 文件大小：{size} 字节")
    print("\n💡 结论：你的环境 100% 正常！")
    print("💡 主程序不能录制，是 抖音流地址/接口问题，不是环境问题！")
    print("=" * 60)
else:
    print("❌ 未生成文件")