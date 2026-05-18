# 小说多角色语音合成系统 - 设计文档

## 1. 系统概述

基于 Qwen3-TTS 实现的小说多角色语音合成系统，支持自动识别小说中的角色，为每个角色配置独特的声音，并输出多角色音频。

## 2. 核心功能

### 2.1 文本解析引擎
- **角色识别**：自动分析文本，识别出角色和旁白
- **对话提取**：提取每个角色的台词和旁白内容
- **情感分析**：分析每句台词的情感（可选）

### 2.2 声音库管理
- **预置声音**：Qwen3-TTS 默认提供的9个声音（Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna, Sohee）
- **声音设计**：使用 VoiceDesign 模型根据描述生成新声音
- **声音克隆**：使用 Base 模型根据参考音频克隆声音
- **声音试听**：在Web界面中试听所有声音
- **角色绑定**：为每个角色绑定一个声音

### 2.3 音频生成引擎
- **批量生成**：为所有角色的台词批量生成音频
- **声音一致性**：通过角色-声音绑定确保同一角色始终使用相同声音
- **音频合并**：将所有角色的音频合并为一个完整的音频文件
- **独立输出**：每个角色的台词分别输出为独立音频文件

### 2.4 Web界面
- **文本上传**：支持上传小说文本文件
- **角色管理**：查看、编辑角色列表，为角色分配声音
- **声音库管理**：查看预置声音，添加自定义声音
- **音频预览**：预览生成的音频
- **下载功能**：下载完整音频或分角色音频

## 3. 技术架构

### 3.1 后端
- **框架**：FastAPI
- **数据库**：SQLite（使用 SQLAlchemy ORM）
- **TTS引擎**：Qwen3-TTS
- **音频处理**：pydub（用于音频合并）

### 3.2 前端
- **技术栈**：原生 HTML + JavaScript + CSS
- **UI框架**：可选使用轻量级CSS框架

### 3.3 数据模型

#### 3.3.1 项目（Project）
- id: 主键
- name: 项目名称
- created_at: 创建时间
- updated_at: 更新时间
- status: 状态（待处理/处理中/已完成）

#### 3.3.2 角色（Character）
- id: 主键
- project_id: 所属项目
- name: 角色名称
- voice_id: 绑定的声音ID
- description: 角色描述（可选）

#### 3.3.3 台词（Line）
- id: 主键
- project_id: 所属项目
- character_id: 角色ID（旁白为null）
- content: 台词内容
- order: 顺序
- emotion: 情感（可选）

#### 3.3.4 声音（Voice）
- id: 主键
- name: 声音名称
- type: 声音类型（predefined/design/clone）
- description: 声音描述
- speaker: 预置声音名称（仅预置声音）
- instruct: 声音设计描述（仅设计声音）
- ref_audio_path: 参考音频路径（仅克隆声音）
- ref_text: 参考文本（仅克隆声音）
- created_at: 创建时间

#### 3.3.5 音频片段（AudioSegment）
- id: 主键
- project_id: 所属项目
- line_id: 对应台词ID
- character_id: 角色ID
- audio_path: 音频文件路径
- duration: 音频时长

## 4. API设计

### 4.1 项目管理
- `POST /api/projects` - 创建项目
- `GET /api/projects` - 获取项目列表
- `GET /api/projects/{id}` - 获取项目详情
- `DELETE /api/projects/{id}` - 删除项目

### 4.2 文本解析
- `POST /api/projects/{id}/parse` - 解析文本，识别角色和台词

### 4.3 角色管理
- `GET /api/projects/{id}/characters` - 获取角色列表
- `PUT /api/projects/{id}/characters/{id}` - 更新角色信息（包括绑定声音）

### 4.4 声音库
- `GET /api/voices` - 获取声音列表
- `POST /api/voices/design` - 创建设计声音
- `POST /api/voices/clone` - 创建克隆声音
- `DELETE /api/voices/{id}` - 删除声音
- `POST /api/voices/{id}/preview` - 试听声音

### 4.5 音频生成
- `POST /api/projects/{id}/generate` - 生成音频
- `GET /api/projects/{id}/audio` - 获取生成的音频
- `GET /api/projects/{id}/download` - 下载音频

## 5. 实现细节

### 5.1 文本解析策略
1. 支持多种格式：
   - `[角色名] 台词` 格式
   - `角色名：台词` 格式
   - 自动识别对话和旁白

### 5.2 声音一致性保证
1. 为每个角色分配唯一的声音ID
2. 生成音频时，根据角色ID获取对应的声音配置
3. 使用角色的声音配置生成音频

### 5.3 音频合并
1. 按顺序拼接所有音频片段
2. 在角色切换时添加适当的停顿
3. 输出完整的音频文件

## 6. 部署方案

### 6.1 环境要求
- Python 3.12+
- CUDA-capable GPU（推荐）
- 至少 16GB 内存

### 6.2 依赖安装
```bash
pip install fastapi uvicorn sqlalchemy pydub
pip install -e ./qwen3-tts-usages/Qwen3-TTS
```

### 6.3 启动命令
```bash
python main.py
```

## 7. 扩展性考虑

### 7.1 多语言支持
- Qwen3-TTS 支持10种语言
- 系统可扩展支持多语言小说

### 7.2 性能优化
- 使用异步处理生成音频
- 支持批量生成
- 缓存已生成的声音配置

### 7.3 未来功能
- 支持更多TTS模型
- 支持音频后处理（降噪、音量均衡）
- 支持多说话人同时对话场景
