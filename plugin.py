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
from .handlers.diary_message_handler import DiaryMessageHandler
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
        self._consolidation_job = None

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

        # 注册零点定时任务
        await self._register_midnight_consolidation()

        logger.info("[ContinuousDiary] 连续日记式记忆系统已启动")

    async def _register_midnight_consolidation(self):
        """注册零点自动合并昨天日记的定时任务"""
        try:
            from src.plugin_system.apis.unified_scheduler import unified_scheduler, TriggerType
            from datetime import datetime, timedelta, time as datetime_time
            
            # 计算下一个零点5分的时间
            now = datetime.now()
            tomorrow = now.date() + timedelta(days=1)
            target_time = datetime.combine(tomorrow, datetime_time(hour=0, minute=5))
            
            # 如果今天还没到0点5分，则今天就触发
            today_target = datetime.combine(now.date(), datetime_time(hour=0, minute=5))
            if now < today_target:
                target_time = today_target
            
            # 使用统一调度器创建每天零点5分的定时任务（循环任务，每24小时触发一次）
            schedule_id = await unified_scheduler.create_schedule(
                callback=self._consolidate_yesterday_diaries,
                trigger_type=TriggerType.TIME,
                trigger_config={
                    "trigger_at": target_time,
                    "interval_seconds": 86400,  # 24小时 = 86400秒
                },
                is_recurring=True,
                task_name="continuous_diary_midnight_consolidation",
                force_overwrite=True,
            )
            
            self._consolidation_job = schedule_id
            logger.info(
                f"[ContinuousDiary] 已注册零点定时任务：下次执行时间 {target_time.strftime('%Y-%m-%d %H:%M:%S')}，"
                f"之后每24小时触发一次 (ID: {schedule_id[:8]}...)"
            )
        except Exception as e:
            logger.error(f"[ContinuousDiary] 注册零点定时任务失败: {e}", exc_info=True)

    async def _consolidate_yesterday_diaries(self):
        """零点定时任务：自动合并所有对话的昨天日记"""
        if not self.manager:
            logger.warning("[ContinuousDiary] 管理器未初始化，跳过零点合并")
            return
        
        from datetime import datetime, timedelta
        
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"[ContinuousDiary] 开始零点合并任务：处理 {yesterday} 的日记")
        
        try:
            # 获取所有对话目录
            data_dir = self.manager.data_dir
            if not data_dir.exists():
                logger.info("[ContinuousDiary] 数据目录不存在，跳过")
                return
            
            conversation_dirs = [d for d in data_dir.iterdir() if d.is_dir()]
            success_count = 0
            fail_count = 0
            
            for conv_dir in conversation_dirs:
                conversation_id = conv_dir.name
                try:
                    # 尝试合并昨天的日记
                    result = await self.manager.consolidate_yesterday(conversation_id, yesterday)
                    if result:
                        success_count += 1
                        logger.debug(f"[ContinuousDiary] ✅ 对话 {conversation_id[:16]}... 昨天日记合并成功")
                    else:
                        logger.debug(f"[ContinuousDiary] ⏭️ 对话 {conversation_id[:16]}... 没有需要合并的日记")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"[ContinuousDiary] ❌ 对话 {conversation_id[:16]}... 合并失败: {e}")
            
            logger.info(
                f"[ContinuousDiary] 零点合并任务完成：成功{success_count}个，失败{fail_count}个，"
                f"共扫描{len(conversation_dirs)}个对话"
            )
        except Exception as e:
            logger.error(f"[ContinuousDiary] 零点合并任务异常: {e}", exc_info=True)

    async def on_plugin_unloaded(self):
        """插件卸载时清理定时任务"""
        if self._consolidation_job:
            try:
                from src.plugin_system.apis.unified_scheduler import unified_scheduler
                await unified_scheduler.remove_schedule(self._consolidation_job)
                logger.info("[ContinuousDiary] 已取消零点定时任务")
            except Exception as e:
                logger.error(f"[ContinuousDiary] 取消定时任务失败: {e}")

    def get_plugin_components(self):
        """注册组件"""
        if not self.config.get("enable", True):
            logger.info("[ContinuousDiary] 插件已禁用，跳过组件注册")
            return []

        if not self.manager:
            # 如果管理器未初始化，先初始化
            import asyncio

            data_dir = Path("data/continuous_diary")
            data_dir.mkdir(parents=True, exist_ok=True)
            self.manager = DiaryManager(data_dir, self.config.get("continuous_diary", {}))

        components = []

        # 1. 注册提示词注入组件
        DiaryPromptComponent.manager = self.manager  # type: ignore
        components.append((DiaryPromptComponent.get_prompt_info(), DiaryPromptComponent))

        # 2. 注册消息事件处理器
        DiaryMessageHandler.manager = self.manager  # type: ignore
        components.append((DiaryMessageHandler.get_handler_info(), DiaryMessageHandler))
        
        # 3. 注册命令组件
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
                "成本可控：用户可调整各层级字数",
                "低耦合：独立数据存储，可随时禁用",
            ],
        }
