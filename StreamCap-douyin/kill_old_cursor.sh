#!/bin/bash
# 清理旧的 Cursor 服务器进程

echo "=========================================="
echo "   清理旧的 Cursor 服务器进程"
echo "=========================================="
echo ""

# 找到所有旧的 Cursor 服务器进程 (10:52启动的)
OLD_PIDS=$(ps aux | grep "1685afce45886aa5579025ac7e077fc3d4369c50" | grep -v grep | awk '{print $2}')

if [ -z "$OLD_PIDS" ]; then
    echo "✓ 没有找到旧的 Cursor 服务器进程"
    exit 0
fi

echo "找到以下旧进程:"
echo "----------------------------------------"
for pid in $OLD_PIDS; do
    info=$(ps -p $pid -o pid,start,cmd= 2>/dev/null)
    if [ ! -z "$info" ]; then
        echo "  $info"
    fi
done
echo ""

# 检查这些进程占用的端口
echo "这些进程占用的端口:"
echo "----------------------------------------"
for pid in $OLD_PIDS; do
    ports=$(lsof -p $pid -i -P -n 2>/dev/null | grep LISTEN | awk '{print $9}' | sed 's/.*://' | sed 's/(.*//')
    if [ ! -z "$ports" ]; then
        echo "  PID $pid 占用端口: $ports"
    fi
done
echo ""

read -p "是否要终止这些旧进程? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "正在终止旧进程..."
    for pid in $OLD_PIDS; do
        kill $pid 2>/dev/null && echo "  ✓ 已终止进程 $pid" || echo "  ✗ 无法终止进程 $pid"
    done
    sleep 2
    
    # 检查是否还有残留进程，强制终止
    REMAINING=$(ps aux | grep "1685afce45886aa5579025ac7e077fc3d4369c50" | grep -v grep | awk '{print $2}')
    if [ ! -z "$REMAINING" ]; then
        echo ""
        echo "发现残留进程，强制终止..."
        for pid in $REMAINING; do
            kill -9 $pid 2>/dev/null && echo "  ✓ 强制终止进程 $pid" || echo "  ✗ 无法终止进程 $pid"
        done
    fi
    
    echo ""
    echo "✓ 清理完成！请重新启动 Cursor"
else
    echo "操作已取消"
fi

