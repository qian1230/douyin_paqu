#!/bin/bash
# 批量修复当前目录及子目录下所有MP4文件

echo "========================================"
echo "🔧 视频修复工具开始运行"
echo "========================================"

# 计数器
total=0
fixed=0
failed=0

# 查找所有MP4文件
while IFS= read -r file; do
    total=$((total + 1))
    echo -ne "\r📁 正在处理: $file"
    
    # 临时文件名
    tmp_file="${file}.tmp.mp4"
    
    # 用ffmpeg修复
    ffmpeg -i "$file" -c copy -movflags +faststart -y "$tmp_file" 2>/dev/null
    
    if [ $? -eq 0 ] && [ -f "$tmp_file" ]; then
        mv "$tmp_file" "$file"
        fixed=$((fixed + 1))
        echo -e "\r✅ 修复成功: $file"
    else
        failed=$((failed + 1))
        echo -e "\r❌ 修复失败: $file"
        [ -f "$tmp_file" ] && rm "$tmp_file"
    fi
    
done < <(find /mnt/disk022/dataset_w/zhibo-video/douyin -type f -name "*.mp4")

echo ""
echo "========================================"
echo "📊 修复统计"
echo "========================================"
echo "总共处理: $total 个视频"
echo "修复成功: $fixed 个"
echo "修复失败: $failed 个"
echo "========================================"
