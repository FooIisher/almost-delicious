# Azure Elasticsearch + Kibana 9.0.0

主机：`azureuser@203.0.113.10`，部署目录：`/home/azureuser/recipe-search`。
配置采用 Elastic 官方 Docker 镜像，固定两个组件均为 9.0.0。
参考：https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-compose

## 访问

在 Mac 终端保持以下 SSH 隧道运行。使用本地 19200 / 15601，避免与本地 Docker 服务端口冲突。

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 \
  -i ${SSH_KEY_PATH} \
  -L 127.0.0.1:19200:127.0.0.1:9200 \
  -L 127.0.0.1:15601:127.0.0.1:5601 azureuser@203.0.113.10
```

Kibana：<http://localhost:15601>，登录用户名 `elastic`。
密码仅保存在云主机的 `.env` 文件中，权限为 600。在云主机终端查看：

```bash
cd /home/azureuser/recipe-search
sed -n 's/^ELASTIC_PASSWORD=//p' .env
```

Elasticsearch：`https://localhost:19200`。客户端需要 `elastic` 认证及 CA 证书。
从 Mac 下载 CA（这是公开证书，不是私钥）：

```bash
scp -i ${SSH_KEY_PATH} \
  azureuser@203.0.113.10:/home/azureuser/recipe-search/certs/ca/ca.crt ./recipe-es-ca.crt
curl --cacert ./recipe-es-ca.crt -u elastic https://localhost:19200
```

curl 会交互式询问密码。不要把服务器地址改成公网直接访问 9200/5601；端口仅监听云主机回环地址。

## 运维（云主机上执行）

```bash
cd /home/azureuser/recipe-search
sudo docker compose ps
sudo docker stats --no-stream
sudo docker compose logs --tail=100 elasticsearch kibana
sudo docker compose stop kibana     # 导入/压测时可释放内存
sudo docker compose start kibana
sudo docker compose down            # 停止容器，保留数据卷
sudo docker compose up -d           # 恢复服务
python3 verify.py                   # 版本、认证、768维向量读写验证
```

`docker compose down -v` 会删除数据卷，请勿作为普通停止命令使用。
容器设置 `restart: unless-stopped`，Docker 已设为开机启动。
数据卷不是备份，删除 Azure VM/磁盘前必须另行导出数据或建立快照备份。

## 4GB 内存配置

ES 容器限额 2560MiB、JVM 堆 1GiB；Kibana 限额 1024MiB、Node 堆 768MiB。
其余内存供操作系统使用。开启认证、ES HTTPS、持久化 Kibana 加密密钥和日志轮转。
当前为单节点，创建 recipe 索引时用 1 个主分片、0 个副本；不在此机器运行 embedding 模型。
全量导入时控制 bulk 批次与并发，必要时暂时停 Kibana。空载验证不代表 5 万条数据的性能测试通过。
未来扩容需要移除 `discovery.type=single-node` 并配置集群发现、节点证书及内网 transport 通信。

## 安装文件

`compose.yaml`：部署配置；`bootstrap.sh`：生成随机密码、TLS 证书并启动服务。
密码、私钥和数据不在此本地目录中。不要将云主机的 `.env`、`.curl-auth` 或 `certs` 上传到仓库。
