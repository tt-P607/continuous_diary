"""
连续日记式记忆插件主类
"""

from pathlib import Path
from typing import Any, Optional, ClassVar

from src.common.logger import get_logger
from src.plugin_system import BasePlugin, register_plugin
from src.plugin_system.base.plugin_metadata import PluginMetadata
from src.plugin_system.base.component_types import PermissionNodeField

from .config_schema import CONFIG_SCHEMA
from .core.diary_manager import DiaryManager
from .handlers.diary_prompt import DiaryPromptComponent
from .commands.diary_commands import DiaryCommand

logger = get_logger("continuous_diary_plugin")


@register_plugin
class ContinuousDiaryPlugin(BasePlugin):
    """连续日记式记忆插件"""

    __plugin_meta__ = PluginMetadata(
        name="Continuous Diary Memory",
        description="用bot的主观视角记录近期对话，像写日记一样提供完整的上下文",
        usage="自动触发，每累积一定消息数自动生成日记总结",
        version="1.0.0",
        author="MoFox-Studio",
        categories=["memory", "enhancement"],
    )

    plugin_name = "continuous_diary_memory"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"

    config_section_descriptions = {
        "continuous_diary": "连续日记式记忆配置",
    }

    config_schema = CONFIG_SCHEMA  # type: ignore
    
    permission_nodes: ClassVar[list[PermissionNodeField]] = [
        PermissionNodeField(
            node_name="command.use",
            description="是否可以使用日记管理命令"
        ),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.manager: Optional[DiaryManager] = None

    async def on_plugin_loaded(self):
        """插件加载时初始化管理器"""
        # 检查是否启用
        if not self.config.get("enable", True):
            logger.info("[ContinuousDiary] 插件已禁用")
            return

        # 创建数据目录
        data_dir = Path("data/continuous_diary")
        data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化管理器
        self.manager = DiaryManager(data_dir, self.config.get("continuous_diary", {}))

        # 启动时检查并补全活跃对话的历史总结
        try:
            await self.manager.startup_completion_check()
        except Exception as e:
            logger.error(f"[ContinuousDiary] 启动检查失败: {e}", exc_info=True)

        logger.info("[ContinuousDiary] 连续日记式记忆系统已启动")

    async def on_plugin_unloaded(self):
        """插件卸载时清理"""
        logger.info("[ContinuousDiary] 插件已卸载")

    def get_plugin_components(self):
        """注册组件"""
        if not self.config.get("enable", True):
            logger.info("[ContinuousDiary] 插件已禁用，跳过组件注册")
            return []

        if not self.manager:
            # 如果管理器未初始化，先初始化
            data_dir = Path("data/continuous_diary")
            data_dir.mkdir(parents=True, exist_ok=True)
            self.manager = DiaryManager(data_dir, self.config.get("continuous_diary", {}))

        components = []

        # 1. 注册提示词注入组件
        DiaryPromptComponent.manager = self.manager  # type: ignore
        components.append((DiaryPromptComponent.get_prompt_info(), DiaryPromptComponent))

        # 2. 注册命令组件
        DiaryCommand.manager = self.manager  # type: ignore
        components.append((DiaryCommand.get_plus_command_info(), DiaryCommand))

        logger.info(f"[ContinuousDiary] 已注册 {len(components)} 个组件")
        return components

    def get_plugin_info(self) -> dict[str, Any]:
        """获取插件信息"""
        return {
            "name": self.plugin_name,
            "display_name": "连续日记式记忆",
            "version": "1.0.0",
            "author": "MoFox-Studio",
            "description": "用bot的主观视角记录近期对话，像写日记一样提供完整的上下文",
            "features": [
                "主观视角日记记录（第一人称'我'）",
                "时间分层：今天详细、昨天简略、前天更简略",
                "智能触发：基于消息数或时间间隔",
                "启动时自动补全缺失的历史日记",
            ],
        }
