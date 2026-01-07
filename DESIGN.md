# 连续日记式记忆插件 - 设计文档

## 🎯 核心设计：每天独立文件 + 统一生成逻辑

### 设计原则
1. **简单直接**：三个时间层（今天/昨天/前天）都用同一套逻辑生成
2. **完全容错**：任何时候都能从数据库重新生成，不依赖历史状态
3. **按需补全**：启动时 + 首次激活时检查，只对活跃对话补全

### 时间基准
- **以每天零点为界**，不是滚动24小时
- **今天** = 今天零点到现在
- **昨天** = 昨天零点到昨天23:59
- **前天** = 前天零点到前天23:59

---

## 📊 数据结构

### 文件组织
```
data/
├── group/
│   └── {群号}_{群名}/
│       ├── 2026-01-05.json  # 前天
│       ├── 2026-01-06.json  # 昨天
│       └── 2026-01-07.json  # 今天
└── private/
    └── {用户ID}_{用户名}/
        └── ...
```

### 单日数据结构
```json
{
  "date": "2026-01-07",
  "summary": {
    "content": "今天的日记内容...",
    "message_count": 150,
    "word_count": 1200,
    "created_at": "2026-01-07T10:30:00",
    "updated_at": "2026-01-07T18:45:00"
  },
  "last_summary_time": "2026-01-07T18:45:00",
  "metadata": {
    "identity": "bot的人设信息...",
    "chat_type": "group",
    "stream_id": "..."
  }
}
```

---

## 🔄 核心流程

### 总结生成（统一逻辑）
```
generate_summary_for_date(conversation_id, target_date, identity, chat_type):
  1. 检查该日期是否已有总结（非强制模式下跳过）
  2. 计算时间范围：当天零点 → 23:59（或现在）
  3. 从数据库读取该时间范围内的消息
  4. 根据日期类型确定字数限制（今天/昨天/前天）
  5. 调用 LLM 生成日记式总结
  6. 保存到对应日期的 JSON 文件
```

### 获取日记内容
```
get_diary_for_prompt(conversation_id):
  1. 检查今天是否有总结（活跃标志）
  2. 如果今天有总结 且 首次请求：
     - 检查昨天/前天是否有总结
     - 没有则自动补全
  3. 读取三天的文件，拼接返回
```

### 启动检查
```
startup_completion_check():
  1. 扫描所有对话目录
  2. 筛选"今天有总结"的对话（活跃标志）
  3. 对这些对话检查昨天/前天
  4. 缺失的自动从数据库生成
```

---

## ⚙️ 配置项

```toml
[continuous_diary]
enable = true
enabled_chat_types = ["group", "private"]

# 群聊触发配置
group_trigger_type = "any"       # time | message | both | any
group_message_threshold = 50
group_time_interval_hours = 6

# 私聊触发配置
private_trigger_type = "any"
private_message_threshold = 30
private_time_interval_hours = 12

# 字数限制
group_today_max_words = 2000
group_yesterday_max_words = 1000
group_older_max_words = 500
private_today_max_words = 1500
private_yesterday_max_words = 800
private_older_max_words = 400

# 存储配置
retention_days = 3
model_context_limit_k = 100
```

---

## 🎨 命令系统

| 命令 | 功能 |
|------|------|
| `/diary` | 显示三天日记状态 + 待处理消息数 |
| `/diary refresh` | 强制刷新所有日记 |

---

## 📝 注入格式

```
【你的日记回顾】
（以下是你用自己的视角记录的最近对话经历）

【今天】
上午10点多小明上线说代码跑不起来...

---

【昨天】
昨天早上大家讨论了...

---

【前天】
前天聊到了周末计划...

---
（以下是最近的原始对话）
```

---

## 🚀 优势

| 特性 | 说明 |
|------|------|
| **统一逻辑** | 三个时间层用同一套代码，好维护 |
| **完全容错** | 任何时候都能从数据库重新生成 |
| **按需补全** | 只对活跃对话补全，不浪费资源 |
| **简单结构** | 每天一个文件，清晰明了 |
| **无状态依赖** | 不依赖"增量合并"，断电也不怕 |
