# cg智能体
完全重新开发

# 启动
 - uv venv

 - uv sync
 - uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8002
 - postman，调试接口： http://localhost:8002/api/v1/agent/chat， json参数： {"message": "机组循环水泵C两年的设备健康情况","user_id":"1", "stream":false}

# 整体流程
https://share.note.youdao.com/s/bM1miTVH
