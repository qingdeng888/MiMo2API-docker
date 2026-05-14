FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目文件
COPY . .

# 没有 config.json 时使用示例配置
RUN test -f config.json || cp config.example.json config.json

# 暴露端口
EXPOSE 8080

# 启动服务
CMD ["python", "main.py"]
