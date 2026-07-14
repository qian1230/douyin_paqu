#!/bin/bash
# StreamCap 快速部署新节点脚本
# 使用方法: ./deploy_node.sh <NODE_ID> <NODE_NAME> <DB_HOST> <DB_USER> <DB_PASSWORD> <DB_NAME> <DOUYIN_COOKIE>

set -e

NODE_ID=$1
NODE_NAME=$2
DB_HOST=$3
DB_USER=$4
DB_PASSWORD=$5
DB_NAME=$6
DOUYIN_COOKIE=$7

if [ -z "$NODE_ID" ] || [ -z "$NODE_NAME" ] || [ -z "$DB_HOST" ] || [ -z "$DOUYIN_COOKIE" ]; then
    echo "用法: $0 <NODE_ID> <NODE_NAME> <DB_HOST> <DB_USER> <DB_PASSWORD> <DB_NAME> <DOUYIN_COOKIE>"
    echo ""
    echo "示例:"
    echo "  $0 node1 '服务器节点1' 192.168.1.100 streamcap_user mypassword streamcap 'your_cookie_string'"
    exit 1
fi

echo "=========================================="
echo "部署 StreamCap 节点"
echo "=========================================="
echo "节点ID: $NODE_ID"
echo "节点名称: $NODE_NAME"
echo "数据库主机: $DB_HOST"
echo "数据库名称: $DB_NAME"
echo ""

# 1. 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python3，请先安装 Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "Python 版本: $PYTHON_VERSION"

# 2. 获取项目目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "项目目录: $PROJECT_DIR"

# 3. 安装依赖
echo ""
echo "安装依赖..."
pip3 install -r requirements.txt --quiet
pip3 install asyncpg psycopg2-binary --quiet

# 4. 创建.env文件
echo ""
echo "创建配置文件..."
cat > .env << EOF
# 节点配置
NODE_ID=$NODE_ID
NODE_NAME=$NODE_NAME
PORT=6006

# 数据库配置（PostgreSQL）
DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASSWORD@$DB_HOST:5432/$DB_NAME

# Cookie配置
DOUYIN_COOKIE=$DOUYIN_COOKIE

# 录制配置
MAX_RECORDING_COUNT=6
MIN_RECORDING_COUNT=6
MAX_MONITORING_ONLY=4

# 时区
TZ=Asia/Shanghai

# 平台配置
PLATFORM=web
HOST=0.0.0.0
EOF

# 5. 创建必要的目录
echo "创建目录结构..."
mkdir -p logs config downloads

# 6. 初始化配置（如果需要）
if [ ! -f "config/user_settings.json" ]; then
    echo "初始化用户配置..."
    cp config/default_settings.json config/user_settings.json
    # 设置默认保存路径
    python3 << PYEOF
import json
with open('config/user_settings.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
config['live_save_path'] = './downloads'
config['record_quality'] = 'LD'
config['video_segment_time'] = '3600'
with open('config/user_settings.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=4)
PYEOF
fi

# 7. 创建systemd服务文件（可选）
echo ""
echo "创建 systemd 服务文件..."
cat > /tmp/streamcap-${NODE_ID}.service << EOF
[Unit]
Description=StreamCap Node ${NODE_ID} - ${NODE_NAME}
After=network.target postgresql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$(which python3):/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$(which python3) $PROJECT_DIR/main.py --web --host 0.0.0.0 --port 6006
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
echo ""
echo "下一步操作："
echo ""
echo "1. 安装 systemd 服务（可选）:"
echo "   sudo cp /tmp/streamcap-${NODE_ID}.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable streamcap-${NODE_ID}"
echo "   sudo systemctl start streamcap-${NODE_ID}"
echo ""
echo "2. 手动启动（测试）:"
echo "   cd $PROJECT_DIR"
echo "   python3 main.py --web --host 0.0.0.0 --port 6006"
echo ""
echo "3. 查看日志:"
echo "   sudo journalctl -u streamcap-${NODE_ID} -f"
echo ""
echo "4. 访问Web界面:"
echo "   http://$(hostname -I | awk '{print $1}'):6006"
echo ""




