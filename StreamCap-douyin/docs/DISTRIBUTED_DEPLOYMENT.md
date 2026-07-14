# StreamCap 分布式部署方案

## 概述

为了突破单个账号的并发限制，实现大规模录制，可以采用多服务器分布式部署方案。每个服务器使用不同的Cookie，共享同一个数据库，实现任务协同和负载均衡。

## 架构设计

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  服务器节点1     │     │  服务器节点2     │     │  服务器节点N     │
│  Cookie: A       │     │  Cookie: B       │     │  Cookie: C       │
│  录制数: 6       │     │  录制数: 6       │     │  录制数: 6       │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────▼─────────────┐
                    │   共享数据库 (PostgreSQL)  │
                    │   - scraped_rooms         │
                    │   - recording_logs        │
                    └───────────────────────────┘
```

## 方案一：共享PostgreSQL数据库（推荐）

### 1. 数据库迁移到PostgreSQL

#### 1.1 安装PostgreSQL

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib

# CentOS/RHEL
sudo yum install postgresql-server postgresql-contrib
sudo postgresql-setup initdb
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### 1.2 创建数据库和用户

```bash
sudo -u postgres psql

# 在PostgreSQL命令行中执行
CREATE DATABASE streamcap;
CREATE USER streamcap_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE streamcap TO streamcap_user;
\q
```

#### 1.3 配置PostgreSQL允许远程连接

编辑 `/etc/postgresql/*/main/postgresql.conf`:
```conf
listen_addresses = '*'
```

编辑 `/etc/postgresql/*/main/pg_hba.conf`:
```
host    streamcap    streamcap_user    0.0.0.0/0    md5
```

重启PostgreSQL:
```bash
sudo systemctl restart postgresql
```

### 2. 修改项目配置

#### 2.1 更新数据库连接

修改 `.env` 文件（每个节点）:
```env
# 使用PostgreSQL替代SQLite
DATABASE_URL=postgresql+asyncpg://streamcap_user:your_secure_password@数据库服务器IP:5432/streamcap

# 节点标识（每个节点不同）
NODE_ID=node1
NODE_NAME=服务器节点1

# Cookie配置（每个节点不同）
DOUYIN_COOKIE=你的Cookie字符串1

# 录制配置
MAX_RECORDING_COUNT=6
MIN_RECORDING_COUNT=6
MAX_MONITORING_ONLY=4
```

#### 2.2 安装PostgreSQL驱动

在 `requirements.txt` 中添加：
```
asyncpg>=0.28.0
psycopg2-binary>=2.9.0
```

### 3. 节点任务分配机制

每个节点只处理分配给自己的任务，避免冲突。可以通过以下方式实现：

#### 方式A：基于节点ID的哈希分配
- 根据 `room_id` 的哈希值分配到不同节点
- 每个节点只处理哈希值匹配的任务

#### 方式B：基于数据库状态标记（推荐）
- 在数据库中为每个任务标记 `assigned_node`
- 每个节点只拉取分配给自己的任务
- 支持动态负载均衡

## 方案二：使用NFS共享SQLite（简单但不推荐）

如果不想迁移到PostgreSQL，可以使用NFS共享SQLite数据库文件：

### 1. 设置NFS服务器

在数据库服务器上：
```bash
sudo apt-get install nfs-kernel-server
sudo mkdir -p /mnt/shared/streamcap
sudo chown nobody:nogroup /mnt/shared/streamcap
sudo chmod 777 /mnt/shared/streamcap

# 编辑 /etc/exports
echo "/mnt/shared/streamcap *(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -a
sudo systemctl restart nfs-kernel-server
```

### 2. 客户端挂载

在每个节点上：
```bash
sudo apt-get install nfs-common
sudo mkdir -p /mnt/streamcap-db
sudo mount -t nfs 数据库服务器IP:/mnt/shared/streamcap /mnt/streamcap-db
```

### 3. 配置数据库路径

在 `.env` 中：
```env
DATABASE_URL=sqlite+aiosqlite:////mnt/streamcap-db/streamcap.db
```

**注意**：SQLite在多写场景下性能较差，建议使用PostgreSQL。

## 快速部署方案

### 1. 创建部署脚本

创建 `scripts/deploy_node.sh`:

```bash
#!/bin/bash
# 快速部署新节点脚本

set -e

NODE_ID=$1
NODE_NAME=$2
DB_HOST=$3
DB_USER=$4
DB_PASSWORD=$5
DB_NAME=$6
DOUYIN_COOKIE=$7

if [ -z "$NODE_ID" ] || [ -z "$NODE_NAME" ] || [ -z "$DB_HOST" ] || [ -z "$DOUYIN_COOKIE" ]; then
    echo "Usage: $0 <NODE_ID> <NODE_NAME> <DB_HOST> <DB_USER> <DB_PASSWORD> <DB_NAME> <DOUYIN_COOKIE>"
    exit 1
fi

echo "部署节点: $NODE_NAME (ID: $NODE_ID)"

# 1. 克隆项目（如果还没有）
if [ ! -d "StreamCap-main" ]; then
    git clone https://github.com/ihmily/StreamCap.git StreamCap-main
    cd StreamCap-main
else
    cd StreamCap-main
    git pull
fi

# 2. 安装依赖
pip3 install -r requirements.txt
pip3 install asyncpg psycopg2-binary

# 3. 创建.env文件
cat > .env << EOF
# 节点配置
NODE_ID=$NODE_ID
NODE_NAME=$NODE_NAME
PORT=6006

# 数据库配置
DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASSWORD@$DB_HOST:5432/$DB_NAME

# Cookie配置
DOUYIN_COOKIE=$DOUYIN_COOKIE

# 录制配置
MAX_RECORDING_COUNT=6
MIN_RECORDING_COUNT=6
MAX_MONITORING_ONLY=4

# 时区
TZ=Asia/Shanghai
EOF

# 4. 创建必要的目录
mkdir -p logs config downloads

# 5. 初始化配置（如果需要）
if [ ! -f "config/user_settings.json" ]; then
    cp config/default_settings.json config/user_settings.json
fi

# 6. 创建systemd服务（可选）
cat > /tmp/streamcap-$NODE_ID.service << EOF
[Unit]
Description=StreamCap Node $NODE_ID
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment="PATH=$(which python3):/usr/local/bin:/usr/bin:/bin"
ExecStart=$(which python3) main.py --web --host 0.0.0.0 --port 6006
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "部署完成！"
echo "启动服务: sudo systemctl start streamcap-$NODE_ID"
echo "查看日志: sudo journalctl -u streamcap-$NODE_ID -f"
```

### 2. 使用Docker Compose部署

创建 `docker-compose.distributed.yml`:

```yaml
version: '3.8'

services:
  streamcap-node1:
    image: ihmily/streamcap
    container_name: streamcap-node1
    environment:
      - NODE_ID=node1
      - NODE_NAME=节点1
      - DATABASE_URL=postgresql+asyncpg://streamcap_user:password@数据库服务器IP:5432/streamcap
      - DOUYIN_COOKIE=${DOUYIN_COOKIE_NODE1}
      - MAX_RECORDING_COUNT=6
      - PORT=6006
      - TZ=Asia/Shanghai
    volumes:
      - ./logs-node1:/app/logs
      - ./config-node1:/app/config
      - ./downloads-node1:/app/downloads
    ports:
      - "6006:6006"
    restart: unless-stopped
    networks:
      - streamcap-network

  streamcap-node2:
    image: ihmily/streamcap
    container_name: streamcap-node2
    environment:
      - NODE_ID=node2
      - NODE_NAME=节点2
      - DATABASE_URL=postgresql+asyncpg://streamcap_user:password@数据库服务器IP:5432/streamcap
      - DOUYIN_COOKIE=${DOUYIN_COOKIE_NODE2}
      - MAX_RECORDING_COUNT=6
      - PORT=6007
      - TZ=Asia/Shanghai
    volumes:
      - ./logs-node2:/app/logs
      - ./config-node2:/app/config
      - ./downloads-node2:/app/downloads
    ports:
      - "6007:6007"
    restart: unless-stopped
    networks:
      - streamcap-network

networks:
  streamcap-network:
    driver: bridge
```

使用方式：
```bash
# 创建.env文件
cat > .env << EOF
DOUYIN_COOKIE_NODE1=你的Cookie1
DOUYIN_COOKIE_NODE2=你的Cookie2
EOF

# 启动所有节点
docker-compose -f docker-compose.distributed.yml up -d
```

## 代码修改建议

### 1. 添加节点标识支持

修改 `app/db/session.py`，添加节点信息：

```python
import os
NODE_ID = os.getenv("NODE_ID", "default")
NODE_NAME = os.getenv("NODE_NAME", "默认节点")
```

### 2. 修改任务分配逻辑

在 `app/core/recording/record_manager.py` 的 `sync_recordings_with_db` 方法中，添加节点过滤：

```python
# 只拉取分配给当前节点的任务，或未分配的任务
from sqlalchemy import or_
result = await db.execute(
    select(ScrapedRoom)
    .where(ScrapedRoom.status.in_([ScrapedRoomStatus.PENDING, ScrapedRoomStatus.RECORDING]))
    .where(or_(
        ScrapedRoom.assigned_node == NODE_ID,  # 分配给当前节点
        ScrapedRoom.assigned_node.is_(None)    # 未分配的任务
    ))
    .order_by(ScrapedRoom.last_scraped.desc())
    .limit(batch_size)
    .offset(offset)
)
```

### 3. 添加节点字段到数据库

需要在 `ScrapedRoom` 模型中添加 `assigned_node` 字段：

```python
assigned_node = Column(String(50), nullable=True, index=True)
```

## 监控和管理

### 1. 查看各节点状态

```sql
-- 查看每个节点分配的任务数
SELECT assigned_node, status, COUNT(*) 
FROM scraped_rooms 
GROUP BY assigned_node, status;

-- 查看各节点录制中的任务
SELECT assigned_node, COUNT(*) 
FROM scraped_rooms 
WHERE status = 'recording' 
GROUP BY assigned_node;
```

### 2. 负载均衡

可以创建一个简单的负载均衡脚本，定期重新分配任务：

```python
# scripts/rebalance_tasks.py
async def rebalance_tasks():
    """重新分配任务，实现负载均衡"""
    # 获取所有活跃节点
    # 统计每个节点的任务数
    # 将任务从负载高的节点转移到负载低的节点
    pass
```

## 注意事项

1. **数据库连接池**：确保PostgreSQL的 `max_connections` 足够大
2. **网络延迟**：确保所有节点到数据库服务器的网络延迟较低
3. **数据一致性**：使用数据库事务确保数据一致性
4. **Cookie管理**：每个节点使用不同的Cookie，避免账号被封
5. **录制文件存储**：每个节点的录制文件可以存储到本地，或使用共享存储（NFS/S3）
6. **日志管理**：建议使用集中式日志管理（如ELK、Loki）

## 扩展性

- **水平扩展**：可以轻松添加更多节点
- **垂直扩展**：可以增加每个节点的录制数量
- **故障转移**：如果某个节点故障，其他节点可以接管其任务

## 总结

推荐使用 **PostgreSQL + 多节点部署** 的方案，这样可以：
- 突破单个账号的并发限制
- 实现任务协同和负载均衡
- 快速部署新节点
- 集中管理所有录制任务




