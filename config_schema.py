"""
配置Schema定义
"""

from src.plugin_system.base.config_types import ConfigField

CONFIG_SCHEMA = {
    "continuous_diary": {
        "enable": ConfigField(
            type=bool,
            default=True,
            description="是否启用连续日记式记忆功能",
            label="启用插件",
        ),
        "enabled_chat_types": ConfigField(
            type=list,
            default=["group", "private"],
            description="适用范围：group(群聊) 和/或 private(私聊)",
            label="适用范围",
            choices=["group", "private"],
        ),
        
        # 群聊触发配置
        "group_trigger_type": ConfigField(
            type=str,
            default="any",
            description="群聊触发方式：time=仅时间 | message=仅消息数 | both=两者都满足(AND) | any=任一满足(OR)",
            label="群聊触发方式",
            choices=["time", "message", "both", "any"],
        ),
        "group_message_threshold": ConfigField(
            type=int,
            default=50,
            description="群聊消息数阈值（当触发方式为message或both时生效）",
            label="群聊消息阈值",
            min=1,
            max=500,
        ),
        "group_time_interval_hours": ConfigField(
            type=int,
            default=6,
            description="群聊时间间隔/小时（当触发方式为time或both时生效）",
            label="群聊时间间隔",
            min=1,
            max=48,
        ),
        
        # 私聊触发配置
        "private_trigger_type": ConfigField(
            type=str,
            default="any",
            description="私聊触发方式：time=仅时间 | message=仅消息数 | both=两者都满足(AND) | any=任一满足(OR)",
            label="私聊触发方式",
            choices=["time", "message", "both", "any"],
        ),
        "private_message_threshold": ConfigField(
            type=int,
            default=30,
            description="私聊消息数阈值（当触发方式为message或both时生效）",
            label="私聊消息阈值",
            min=1,
            max=500,
        ),
        "private_time_interval_hours": ConfigField(
            type=int,
            default=12,
            description="私聊时间间隔/小时（当触发方式为time或both时生效）",
            label="私聊时间间隔",
            min=1,
            max=48,
        ),
        
        # 字数限制（按时间段动态分配，群聊/私聊独立配置）
        # 今天的字数会根据时间段自动调整：早上0-8点33%、中午8-16点67%、晚上16-24点100%
        "group_today_max_words": ConfigField(
            type=int,
            default=2000,
            description="群聊今天的最大字数（动态分配：早0-8点33%，中8-16点67%，晚16-24点100%）",
            label="群聊今天最大字数",
            min=100,
            max=10000,
        ),
        "group_yesterday_max_words": ConfigField(
            type=int,
            default=1000,
            description="群聊昨天的最大字数",
            label="群聊昨天最大字数",
            min=50,
            max=5000,
        ),
        "group_older_max_words": ConfigField(
            type=int,
            default=500,
            description="群聊更早的最大字数",
            label="群聊更早最大字数",
            min=50,
            max=5000,
        ),
        "private_today_max_words": ConfigField(
            type=int,
            default=1500,
            description="私聊今天的最大字数（动态分配：早0-8点33%，中8-16点67%，晚16-24点100%）",
            label="私聊今天最大字数",
            min=100,
            max=10000,
        ),
        "private_yesterday_max_words": ConfigField(
            type=int,
            default=800,
            description="私聊昨天的最大字数",
            label="私聊昨天最大字数",
            min=50,
            max=5000,
        ),
        "private_older_max_words": ConfigField(
            type=int,
            default=400,
            description="私聊更早的最大字数",
            label="私聊更早最大字数",
            min=50,
            max=5000,
        ),
        
        # 存储配置
        "retention_days": ConfigField(
            type=int,
            default=3,
            description="总结保留天数（今天+昨天+前天=3天），超过此天数的总结将被清理",
            label="保留天数",
            min=2,
            max=30,
        ),
        
        # 模型上下文配置
        "model_context_limit_k": ConfigField(
            type=int,
            default=100,
            description="模型上下文能力（单位：k tokens），如果内容超过此限制将均匀分段。推荐设置为模型实际能力的70-80%",
            label="模型上下文限制(k)",
            min=10,
            max=1000,
        ),
        
        # 模型配置
        "model_name": ConfigField(
            type=str,
            default="",
            description="用于生成日记的模型名称（留空则使用默认回复模型）。模型必须在 model_config.toml 中已定义。支持多个模型用逗号分隔，会按顺序尝试并自动重试",
            label="模型名称",
        ),
    },
}

