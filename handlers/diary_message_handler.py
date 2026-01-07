"""
消息事件处理器 - 已废弃
日记系统现在直接从数据库读取消息，不再需要事件处理器收集消息
保留此文件仅为兼容性考虑
"""

from typing import Any, ClassVar, TYPE_CHECKING

from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager


class DiaryMessageHandler(BaseEventHandler):
    """消息事件处理器 - 已废弃，不再使用"""

    handler_name = "diary_message_handler"
    handler_description = "已废弃 - 日记系统现在直接从数据库读取"

    # 不再订阅任何事件
    init_subscribe: ClassVar[list[EventType]] = []

    manager: ClassVar["DiaryManager | None"] = None

    async def execute(self, params: dict) -> HandlerResult:
        """不执行任何操作"""
        return HandlerResult(success=True, continue_process=True)
