# zhenxun_claude_bot
自用插件
只要修改写两个参数就行
# API配置
API_URL = "*********"
API_KEY = "*********"

# 添加模型配置
AVAILABLE_MODELS = {
    "claude": "claude-3-5-sonnet",
    "gpt4": "gpt-4o",
    "gemini": "gemini-1.5-pro"
}
current_model = "claude-3-5-sonnet"  # 默认模型
