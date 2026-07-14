import os
import subprocess
import glob
from tqdm import tqdm
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# ============================================
# 配置路径
# ============================================
BASE_DIR = "/mnt/dataset1/lipreading/mpc/preprocess_datasets"
SUB_DIRS = [ 'AIShell']
NUM_WORKERS = 72
# ============================================

def get_video_duration(file_path):
    """使用 ffprobe 获取视频时长（秒）"""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception as e:
        return 0

def process_file(file_path):
    """处理单个文件，返回时长"""
    duration = get_video_duration(file_path)
    return duration

def process_directory(sub_dir):
    """处理单个目录，返回统计信息"""
    full_path = os.path.join(BASE_DIR, sub_dir)
    
    if not os.path.exists(full_path):
        return {
            '文件夹': sub_dir,
            '文件数': 0,
            '成功读取': 0,
            '总时长(秒)': 0,
            '总时长(小时)': 0,
            '平均时长(秒)': 0
        }
    
    # 查找所有mp4文件
    mp4_files = glob.glob(os.path.join(full_path, '**', '*.mp4'), recursive=True)
    file_count = len(mp4_files)
    
    if file_count == 0:
        return {
            '文件夹': sub_dir,
            '文件数': 0,
            '成功读取': 0,
            '总时长(秒)': 0,
            '总时长(小时)': 0,
            '平均时长(秒)': 0
        }
    
    # 多进程计算时长
    total_duration = 0
    success_count = 0
    
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(process_file, f): f for f in mp4_files}
        
        for future in tqdm(as_completed(futures), total=file_count, desc=f"   {sub_dir}", leave=False):
            try:
                duration = future.result()
                if duration > 0:
                    total_duration += duration
                    success_count += 1
            except Exception as e:
                pass
    
    total_hours = total_duration / 3600
    
    return {
        '文件夹': sub_dir,
        '文件数': file_count,
        '成功读取': success_count,
        '总时长(秒)': total_duration,
        '总时长(小时)': total_hours,
        '平均时长(秒)': total_duration / file_count if file_count > 0 else 0
    }

print("="*60)
print("MP4文件时长统计 (多进程加速)")
print("="*60)
print(f"基础目录: {BASE_DIR}")
print(f"使用进程数: {NUM_WORKERS}")
print()

results = []

# 串行处理每个目录（目录内多进程）
for sub_dir in SUB_DIRS:
    print(f"正在处理: {sub_dir}")
    result = process_directory(sub_dir)
    results.append(result)
    
    if result['文件数'] > 0:
        print(f"   ✅ 成功读取: {result['成功读取']}/{result['文件数']} 个文件")
        print(f"   📊 总时长: {result['总时长(小时)']:.2f} 小时")
    else:
        print(f"   ⚠️ 未找到MP4文件或目录不存在")
    print()

# 输出汇总表格
print("="*60)
print("📊 统计汇总")
print("="*60)

df = pd.DataFrame(results)
print(df.to_string(index=False))

# 保存到CSV
output_csv = os.path.join(BASE_DIR, 'mp4_statistics.csv')
df.to_csv(output_csv, index=False)
print(f"\n💾 统计结果已保存到: {output_csv}")

# 总计
total_files = df['文件数'].sum()
total_hours = df['总时长(小时)'].sum()
print(f"\n📈 总计:")
print(f"   总文件数: {total_files:,}")
print(f"   总时长: {total_hours:.2f} 小时")