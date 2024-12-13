from nonebot import on_message
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.rule import to_me, keyword
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
import json
import aiohttp
from typing import Tuple
import asyncio
from asyncio import Semaphore
import time
from nonebot.permission import SUPERUSER
from nonebot import on_command

from zhenxun.configs.config import Config
from zhenxun.configs.path_config import TEMP_PATH
from zhenxun.configs.utils import PluginExtraData, RegisterConfig
from zhenxun.services.log import logger
from zhenxun.utils.http_utils import AsyncHttpx
from zhenxun.utils.message import MessageUtils
from zhenxun.utils.withdraw_manage import WithdrawManager

# API配置
API_URL = "************"
API_KEY = "************"

# 并发控制
MAX_CONCURRENT_REQUESTS = 3
REQUEST_SEMAPHORE = Semaphore(MAX_CONCURRENT_REQUESTS)
LAST_REQUEST_TIME = 0
MIN_REQUEST_INTERVAL = 10  # 最小请求间隔(秒)

# 添加模型配置
AVAILABLE_MODELS = {
    "claude": "claude-3-5-sonnet",
    "gpt4": "gpt-4o",
    "gemini": "gemini-1.5-pro"
}
current_model = "claude-3-5-sonnet"  # 默认模型

# 添加模型名称反查字典
MODEL_NAMES = {v: k for k, v in AVAILABLE_MODELS.items()}

__zx_plugin_name__ = "claude"
__plugin_usage__ = """
usage：
    ChatGPT AI对话
    指令：
        1. @机器人 你的问题
        2. ai 你的问题
        3. gpt 你的问题
        4. chat 你的问题
        5. 切换模型 模型名
        6. 当前模型
""".strip()
__plugin_des__ = "claude AI对话助手"
__plugin_cmd__ = ["@机器人", "ai", "gpt", "chat", "切换模型", "当前模型"]
__plugin_version__ = 0.1
__plugin_author__ = 'tafiny'
__plugin_settings__ = {
    "level": 5,
    "default_status": True,
    "limit_superuser": False,
    "cmd": ["@机器人"],
}

__plugin_meta__ = PluginMetadata(
    name="claude",
    description="使用 claude 的 Nonebot 插件",
    usage="""
    @机器人 你的问题
    示例: @机器人 你的问题
    """.strip(),
    extra=PluginExtraData(
        author="tafiny",
        version="0.1",
        configs=[
            RegisterConfig(
                key="WITHDRAW_CHATGPT_MESSAGE",
                value=(0, 1),
                help="自动撤回，参1：延迟撤回claude时间(秒)，0 为关闭 | 参2：监控聊天类型，0(私聊) 1(群聊) 2(群聊+私聊)",
                default_value=(0, 1),
                type=Tuple[int, int],
            ),
        ],
    ).dict(),
)

history = [
    {"role": "system", "content": "你是一个有帮助的AI助手,专门为用户提供安全、准确的回答。你会拒绝一切涉及恐怖主义，种族歧视，暴力等问题的回答。"}
]

async def wait_for_interval():
    """确保请求间隔至少10秒"""
    global LAST_REQUEST_TIME
    current_time = time.time()
    if current_time - LAST_REQUEST_TIME < MIN_REQUEST_INTERVAL:
        await asyncio.sleep(MIN_REQUEST_INTERVAL - (current_time - LAST_REQUEST_TIME))
    LAST_REQUEST_TIME = time.time()

async def chat(query, history):
    history.append({
        "role": "user",
        "content": query
    })
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }
    
    data = {
        "model": current_model,
        "messages": history,
        "temperature": 0.7,
        "stream": True
    }
    
    logger.info(f"使用模型 {current_model} 处理请求")  # 添加日志
    
    async with REQUEST_SEMAPHORE:
        try:
            await wait_for_interval()
            
            async with aiohttp.ClientSession() as session:
                async with session.post(API_URL, headers=headers, json=data) as response:
                    if response.status != 200:
                        logger.error(f"API错误: status={response.status}")
                        return f"API请求失败: HTTP {response.status}"
                    
                    # 处理流式响应
                    full_response = ""
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            if line == 'data: [DONE]':
                                break
                            try:
                                json_str = line[6:]  # 去掉 "data: " 前缀
                                data = json.loads(json_str)
                                if 'choices' in data and len(data['choices']) > 0:
                                    delta = data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        content = delta['content']
                                        full_response += content
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON解析错误: {e}")
                                continue
                    
                    # 添加到历史记录
                    if full_response:
                        history.append({
                            "role": "assistant",
                            "content": full_response
                        })
                        return full_response
                    return "未能获取有效响应"
                    
        except Exception as e:
            logger.error(f"请求异常: {str(e)}")
            return f"请求出错: {str(e)}"

# 定义触发关键词
KEYWORDS = ["ai", "gpt", "chat"]

# 保留原有的@触发器
xinhuo_at = on_message(rule=to_me(), priority=100, block=True)

# 添加关键词触发器
xinhuo_keyword = on_message(priority=90, block=True)

async def handle_ai_message(bot: Bot, event: Event, user_input: str, matcher):
    """统一处理AI消息的函数"""
    answer = await chat(user_input, history)
    msg = await matcher.send(answer)
    
    # 使用WithdrawManager处理消息撤回
    withdraw_config = Config.get_config("claude_bot", "WITHDRAW_CHATGPT_MESSAGE")
    withdraw_time, chat_type = withdraw_config
    
    if withdraw_time > 0:
        if (chat_type == 0 and isinstance(event, MessageEvent) and not isinstance(event, GroupMessageEvent)) or \
           (chat_type == 1 and isinstance(event, GroupMessageEvent)) or \
           (chat_type == 2):
            WithdrawManager.add_withdraw_message(event, msg, withdraw_time)

@xinhuo_at.handle()
async def handle_at(bot: Bot, event: Event):
    """处理@消息"""
    if not isinstance(event, MessageEvent):
        return

    user_input = str(event.message).strip()
    if not user_input:
        return

    await handle_ai_message(bot, event, user_input, xinhuo_at)

@xinhuo_keyword.handle()
async def handle_keyword(bot: Bot, event: Event):
    """处理关键词触发消息"""
    if not isinstance(event, MessageEvent):
        return
        
    msg = str(event.message).strip().lower()
    
    # 检查是否以关键词开头
    is_triggered = False
    trigger_word = ""
    for kw in KEYWORDS:
        if msg.startswith(kw + " "):
            is_triggered = True
            trigger_word = kw
            break
            
    if not is_triggered:
        return
        
    # 移除触发词,获取实际问题内容
    user_input = msg[len(trigger_word):].strip()
    if not user_input:
        return

    await handle_ai_message(bot, event, user_input, xinhuo_keyword)

# 添加模型切��命令
switch_model = on_command("切换模型", permission=SUPERUSER, priority=10, block=True)

@switch_model.handle()
async def handle_switch_model(bot: Bot, event: Event):
    if not isinstance(event, MessageEvent):
        return
        
    # 获取命令后的参数
    message = str(event.get_message()).strip()
    # 移除"切换模型"命令本身
    args = message.replace("切换模型", "").strip().lower()
    
    if not args:
        model_list = "\n".join([f"- {k}" for k in AVAILABLE_MODELS.keys()])
        await switch_model.finish(f"请指定要切换的模型:\n{model_list}")
        return
    
    # 添加日志调试
    logger.info(f"切换模型命令参数: '{args}'")
    logger.info(f"可用模型: {list(AVAILABLE_MODELS.keys())}")
    
    model_key = args
    if model_key not in AVAILABLE_MODELS:
        model_list = "\n".join([f"- {k}" for k in AVAILABLE_MODELS.keys()])
        await switch_model.finish(
            f"不支持的模型类型: '{model_key}'\n"
            f"可用模型:\n{model_list}"
        )
        return
        
    global current_model
    old_model = MODEL_NAMES.get(current_model, current_model)
    current_model = AVAILABLE_MODELS[model_key]
    
    # 添加日志
    logger.info(f"模型切换: {old_model} -> {model_key} ({current_model})")
    
    # 添加更详细的成功提示
    await switch_model.finish(
        f"模型切换成功!\n"
        f"从 {old_model} 切换到 {model_key}\n"
        f"可以开始对话了"
    )

# 添加当前模型查询命令
check_model = on_command("当前模型", priority=10, block=True)

@check_model.handle()
async def handle_check_model(bot: Bot, event: Event):
    model_name = MODEL_NAMES.get(current_model, current_model)
    await check_model.finish(f"当前使用的模型是: {model_name}")
