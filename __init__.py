"""
连续日记式记忆插件 (Continuous Diary Memory Plugin)

用bot的主观视角记录近期对话，像写日记一样提供完整的上下文。
支持时间分层：今天详细、昨天简略、前天更简略。
"""

from src.plugin_system.base.plugin_metadata import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="continuous_diary_memory",
    description="用bot的主观视角记录近期对话，像写日记一样提供完整的上下文。时间分层：今天详细、昨天简略、前天更简略。",
    usage="自动触发，每累积一定消息数自动生成日记总结，在回复时自动注入到提示词中。",
    version="1.0.0",
    author="言柒",
    license="GPL-v3.0-or-later",
    repository_url="https://github.com/tt-P607/continuous_diary",
    keywords=["memory", "diary", "context", "continuous", "subjective"],
    categories=["memory", "enhancement", "personality"],
    extra={
        "is_built_in": False,
    },
)
