# 快速开始：分布式部署指南

## 一、准备工作

### 1. 准备PostgreSQL数据库

在一台服务器上安装并配置PostgreSQL：

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib

# 创建数据库
sudo -u postgres psql
CREATE DATABASE streamcap;
CREATE USER streamcap_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE streamcap TO streamcap_user;
\q
```

### 2. 准备多个Cookie

为每个节点准备不同的抖音Cookie，避免账号限制。

## 二、快速部署方案

### 方案A：使用部署脚本（推荐）

#### 1. 在第一个节点部署

```bash
# 克隆项目
git clone https://github.com/ihmily/StreamCap.git StreamCap-main
cd StreamCap-main

# 运行部署脚本
./scripts/deploy_node.sh node1 "服务器节点1" 192.168.1.100 streamcap_user mypassword streamcap "你的Cookie1"
```

#### 2. 在第二个节点部署

```bash
# 在新服务器上克隆项目
git clone https://github.com/ihmily/StreamCap.git StreamCap-main
cd StreamCap-main

# 运行部署脚本（使用不同的节点ID和Cookie）
./scripts/deploy_node.sh node2 "服务器节点2" 192.168.1.100 streamcap_user mypassword streamcap "你的Cookie2"
```

#### 3. 启动服务

```bash
# 方式1：使用systemd（推荐）
sudo cp /tmp/streamcap-node1.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable streamcap-node1
sudo systemctl start streamcap-node1

# 方式2：手动启动（测试）
python3 main.py --web --host 0.0.0.0 --port 6006
```

### 方案B：使用Docker Compose

#### 1. 创建配置文件

创建 `.env` 文件：

```env
# 数据库配置（所有节点共享）
DATABASE_URL=postgresql+asyncpg://streamcap_user:your_password@192.168.1.100:5432/streamcap

# 各节点的Cookie
DOUYIN_COOKIE_NODE1=你的Cookie1
DOUYIN_COOKIE_NODE2=你的Cookie2
DOUYIN_COOKIE_NODE3=你的Cookie3
```

#### 2. 启动所有节点

```bash
docker-compose -f docker-compose.distributed.yml up -d
```

#### 3. 查看日志

```bash
# 查看所有节点日志
docker-compose -f docker-compose.distributed.yml logs -f

# 查看单个节点日志
docker logs -f streamcap-node1
```

## 三、验证部署

### 1. 检查节点状态

访问各节点的Web界面：
- 节点1: http://节点1IP:6006
- 节点2: http://节点2IP:6007

### 2. 检查数据库连接

在数据库中执行：

```sql
-- 查看各节点分配的任务
SELECT assigned_node, status, COUNT(*) 
FROM scraped_rooms 
GROUP BY assigned_node, status;

-- 查看各节点录制中的任务
SELECT assigned_node, COUNT(*) 
FROM scraped_rooms 
WHERE status = 'recording' 
GROUP BY assigned_node;
```

## 四、任务分配机制

系统会自动将任务分配给各节点：

1. **新任务**：未分配的任务会被第一个拉取的节点自动标记
2. **已分配任务**：每个节点只处理分配给自己的任务
3. **负载均衡**：可以通过重新分配任务实现负载均衡

## 五、常见问题

### Q1: 如何添加更多节点？

只需在新服务器上运行部署脚本，使用新的节点ID和Cookie即可。

### Q2: 如何修改节点配置？

编辑对应节点的 `.env` 文件，然后重启服务。

### Q3: 数据库连接失败怎么办？

1. 检查PostgreSQL是否允许远程连接
2. 检查防火墙设置
3. 检查数据库用户名和密码是否正确

### Q4: 如何查看各节点的录制情况？

访问各节点的Web界面，或查询数据库中的 `recording_logs` 表。

### Q5: 如何实现负载均衡？

可以定期运行任务重新分配脚本，将任务从负载高的节点转移到负载低的节点。

## 六、性能优化建议

1. **数据库优化**：
   - 确保PostgreSQL的 `max_connections` 足够大
   - 为 `assigned_node` 和 `status` 字段创建索引

2. **网络优化**：
   - 确保所有节点到数据库服务器的网络延迟较低
   - 考虑使用内网连接

3. **存储优化**：
   - 每个节点的录制文件可以存储到本地
   - 或使用共享存储（NFS/S3）统一管理

4. **监控建议**：
   - 使用集中式日志管理（如ELK、Loki）
   - 监控各节点的CPU、内存、磁盘使用情况

## 七、扩展性

- **水平扩展**：可以轻松添加更多节点，只需运行部署脚本
- **垂直扩展**：可以增加每个节点的录制数量（修改 `MAX_RECORDING_COUNT`）
- **故障转移**：如果某个节点故障，可以手动将任务重新分配给其他节点




