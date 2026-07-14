#!/bin/bash
# 查找所有 Cursor 相关进程和占用的端口

echo "=========================================="
echo "   Cursor 进程和端口占用情况"
echo "=========================================="
echo ""

echo "【当前运行的所有 Cursor 服务器进程】"
echo "----------------------------------------"
ps aux | grep cursor-server | grep -v grep | awk '{printf "进程ID: %-8s | 启动时间: %-8s\n", $2, $9}'
echo ""

echo "【所有 Node 进程占用的端口】"
echo "----------------------------------------"
lsof -i -P -n 2>/dev/null | grep LISTEN | grep node | while read line; do
    pid=$(echo $line | awk '{print $2}')
    port=$(echo $line | sed 's/.*:\([0-9]*\) (LISTEN).*/\1/')
    proc_info=$(ps -p $pid -o cmd= 2>/dev/null | cut -c1-80)
    start_time=$(ps -p $pid -o lstart= 2>/dev/null | awk '{print $4}')
    echo "端口: $port | PID: $pid | 启动时间: $start_time"
    echo "  命令: $proc_info"
    echo ""
done

echo "【旧的 Cursor 服务器实例 (10:52启动)】"
echo "----------------------------------------"
echo "以下进程可能是旧的 Cursor 实例，可能造成端口冲突:"
ps aux | grep "1685afce45886aa5579025ac7e077fc3d4369c50" | grep -v grep | awk '{printf "  PID: %-8s | 启动: %s\n", $2, $9}'
echo ""

echo "【新的 Cursor 服务器实例 (13:33启动)】"
echo "----------------------------------------"
ps aux | grep "b3573281c4775bfc6bba466bf6563d3d498d1070" | grep -v grep | awk '{printf "  PID: %-8s | 启动: %s\n", $2, $9}'
echo ""

echo "=========================================="
echo "提示: 如果要清理旧进程，运行以下命令:"
echo "  kill_old_cursor.sh"
echo "=========================================="

