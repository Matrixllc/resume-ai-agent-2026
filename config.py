# config.py


import os


def _ensure_local_ollama_bypasses_proxy(ollama_host: str) -> None:
    """
    当 Ollama 运行在本机时，确保 Python HTTP 客户端不会错误地走系统代理。
    这能避免本地 embedding/chat 请求被代理拦截后返回 502。
    """
    local_hosts = ("localhost", "127.0.0.1")
    if not any(host in ollama_host for host in local_hosts):
        return

    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    entries = [item.strip() for item in existing.split(",") if item.strip()]
    for host in local_hosts:
        if host not in entries:
            entries.append(host)

    value = ",".join(entries)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value

def get_config():
    """
    提供应用程序的配置。
    """
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    chat_provider = "openai" if openai_api_key else "ollama"
    config = {
        "model": {
            "chat_provider": chat_provider,
            "openai_model": "gpt-4.1-mini",
            "llm_model": "llama3:latest",  # 您的Ollama模型名称
            "ollama_embedding_model": "bge-m3", # Ollama嵌入模型名称
            "collection_name": "resume_collection" # ChromaDB collection 名称
        },
        "env": {
            "ollama_host": "http://localhost:11434",  # Ollama服务地址
            "ollama_timeout": 120.0, # Ollama请求超时时间（秒）
            "openai_api_key": openai_api_key,
            "openai_base_url": "https://api.openai.com/v1"
        },
        "performance": {
            "retrieval_top_k": 3,         # 问答时检索更少片段，降低上下文体积
            "extraction_max_chars": 3500, # 结构化提取时限制输入长度，避免本地模型过慢
            "llm_temperature": 0.0,       # 更稳定、更少发散
            "llm_num_predict": 900        # 限制生成长度，减少超长输出
        }
    }
    _ensure_local_ollama_bypasses_proxy(config["env"]["ollama_host"])
    return config
