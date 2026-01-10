"""
消息事件处理器
通过监听消息事件来更新内存计数器，实现轻量级的主动触发检查
"""

from typing import Any, ClassVar, TYPE_CHECKING

from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.common.logger import get_logger

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager

logger = get_logger("continuous_diary.message_handler")


class DiaryMessageHandler(BaseEventHandler):
    """消息事件处理器 - 用于驱动日记生成"""

    handler_name = "diary_message_handler"
    handler_description = "监听消息并更新日记计数器"

    # 订阅消息事件
    init_subscribe: ClassVar[list[EventType]] = [
        EventType.ON_MESSAGE
    ]

    manager: ClassVar["DiaryManager | None"] = None

    async def execute(self, params: dict | None) -> tuple[bool, bool, str | None]:
        """记录消息并尝试触发总结"""
        if not self.manager or not params:
            return True, True, None

        try:
            # 提取 stream_id
            chat_id = params.get("chat_id") or getattr(params, "chat_id", None)
            
            if chat_id:
                # 记录消息到内存计数器
                self.manager.record_message(chat_id)
                
        except Exception as e:
            logger.error(f"[DiaryMessageHandler] 处理消息失败: {e}")

        return True, True, None
