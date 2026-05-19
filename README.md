# 小说多角色语音合成系统

基于 Qwen3-TTS 实现的小说多角色语音合成系统，支持自动识别小说中的角色，为每个角色配置独特的声音，并输出多角色音频。

## 功能特性

- **文本解析**：自动分析文本，识别角色和旁白
- **声音库管理**：预置Qwen默认声音 + 用户自定义声音（语音设计/克隆）
- **角色-声音绑定**：每个角色绑定一个声音，确保一致性
- **音频生成引擎**：批量生成多角色音频，支持合并和独立输出
- **Web界面**：上传文本、角色管理、声音库管理、音频预览和下载

## 技术栈

- **后端**：FastAPI
- **数据库**：SQLite
- **TTS引擎**：Qwen3-TTS
- **音频处理**：soundfile, pydub

## 安装

### 环境要求

- Python 3.12+
- CUDA-capable GPU（推荐）
- 至少 16GB 内存

### 安装步骤

1. 克隆项目

```bash
git clone <repository-url>
cd novel_tts
```

2. 创建虚拟环境

```bash
conda create -n novel_tts python=3.12 -y
conda activate novel_tts
```

3. 安装依赖

```bash
pip install -r requirements.txt
```

4. 安装Qwen3-TTS

```bash
cd qwen3-tts-usages/Qwen3-TTS
pip install -e .
cd ../..
```

5. 启动服务

```bash
python main.py
```

服务将在 http://localhost:7860 启动

## Docker 部署

### 前置条件

- [Docker](https://docs.docker.com/get-docker/) 与 [Docker Compose](https://docs.docker.com/compose/)
- NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)（推荐）

### 快速启动

```bash
# 构建并启动（默认端口 7860）
docker compose up -d --build

# 查看日志
docker compose logs -f novel-tts
```

浏览器访问：http://localhost:7860

### 模型与配置

- 容器默认使用 `config.docker.json`（HuggingFace 模型 ID），首次运行会自动下载到 `./models` 卷。
- 若已有本地权重，可编辑 `config.json` 中的模型路径，并在 `docker-compose.yml` 中挂载：

```yaml
volumes:
  - ./config.json:/app/config.json:ro
  - /你的模型目录:/models:ro
```

### 仅 CPU（调试用）

```bash
docker build -f Dockerfile.cpu -t novel-tts:cpu .
docker run -p 7860:7860 -v "$(pwd)/models:/models/huggingface" novel-tts:cpu
```

## 配置文件

系统配置文件为 `config.json`，包含以下配置项：

```json
{
  "models": {
    "custom_voice": {
      "name": "Qwen/Qwen3-TTS-12Hz-{model_size}-CustomVoice",
      "description": "预置声音生成模型"
    },
    "voice_design": {
      "name": "Qwen/Qwen3-TTS-12Hz-{model_size}-VoiceDesign",
      "description": "声音设计模型"
    },
    "base": {
      "name": "Qwen/Qwen3-TTS-12Hz-{model_size}-Base",
      "description": "声音克隆模型"
    }
  },
  "model_size": "1.7B",
  "device": "cuda:0",
  "dtype": "bfloat16",
  "attn_implementation": "flash_attention_2",
  "language": "Chinese",
  "output_sample_rate": 24000,
  "max_new_tokens": 2048,
  "temperature": 0.9,
  "top_p": 1.0,
  "top_k": 50,
  "repetition_penalty": 1.05,
  "audio": {
    "pause_duration": 0.5,
    "output_format": "wav"
  },
  "paths": {
    "model_cache_dir": "./models",
    "audio_output_dir": "./static/audio",
    "upload_dir": "./static/uploads"
  }
}
```

### 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `model_size` | 模型大小，可选 `0.6B` 或 `1.7B` | `1.7B` |
| `device` | 设备，如 `cuda:0` 或 `cpu` | `cuda:0` |
| `dtype` | 数据类型，可选 `bfloat16`, `float16`, `float32` | `bfloat16` |
| `attn_implementation` | 注意力实现，可选 `flash_attention_2` 或 `eager` | `flash_attention_2` |
| `language` | 默认语言 | `Chinese` |
| `audio.pause_duration` | 音频片段间停顿时间（秒） | `0.5` |

## 日志系统

系统提供完善的日志记录功能，支持以下特性：

### 日志配置

- **日志级别**：DEBUG, INFO, WARNING, ERROR, CRITICAL
- **日志文件**：`logs/novel_tts.log`
- **日志轮转**：单个文件最大 10MB，保留 5 个备份
- **控制台输出**：带颜色输出

### 日志内容

系统会记录以下信息：

- **系统信息**：操作系统、Python版本、PyTorch版本、CUDA信息
- **模型加载**：模型名称、设备、数据类型、加载时间
- **音频生成**：文本长度、说话人、语言、生成时间
- **错误信息**：详细的错误堆栈

### 日志API

```bash
# 获取日志
curl http://localhost:8000/api/logs?lines=100

# 重新加载配置
curl -X POST http://localhost:8000/api/config/reload
```

## 使用方法

### 1. 上传小说文本

在Web界面中，输入小说文本并创建项目。系统支持以下格式：

- `[角色名] 台词`
- `角色名：台词`
- `"角色名"说 台词`

### 2. 解析文本

点击"解析"按钮，系统会自动识别角色和台词。

### 3. 配置声音

在声音库管理中，可以：

- 查看预置声音
- 创建设计声音（使用VoiceDesign模型）
- 创建克隆声音（使用Base模型）
- 试听声音

### 4. 生成音频

点击"生成音频"按钮，系统会为每个角色的台词生成音频，并合并为一个完整的音频文件。

### 5. 下载音频

生成完成后，可以下载完整的音频文件。

## API文档

启动服务后，访问 http://localhost:8000/docs 查看API文档。

### 新增API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取系统配置 |
| POST | `/api/config/reload` | 重新加载配置 |
| GET | `/api/logs` | 获取日志内容 |

## 项目结构

```
novel_tts/
├── main.py                    # FastAPI主程序入口
├── config.json                # 系统配置文件
├── src/
│   ├── text_parser.py         # 文本解析引擎
│   ├── database.py            # 数据库模型
│   ├── audio_generator.py     # 音频生成引擎
│   ├── config_manager.py      # 配置管理
│   └── logger.py              # 日志系统
├── logs/                      # 日志目录
│   └── novel_tts.log        # 日志文件
├── static/                    # 静态文件
│   ├── audio/                # 生成的音频文件
│   └── uploads/              # 上传的文件
├── docs/                      # 文档
│   └── design.md             # 设计文档
├── requirements.txt           # 依赖
└── README.md                  # 说明文档
```

## 预置声音

Qwen3-TTS 提供9个预置声音：

| 声音名称 | 描述 | 母语 |
|---------|------|------|
| Vivian | 明亮、略带锐利的年轻女声 | 中文 |
| Serena | 温暖、温柔的年轻女声 | 中文 |
| Uncle_Fu | 低沉、醇厚的成熟男声 | 中文 |
| Dylan | 年轻、清晰的北京男声 | 中文（北京方言） |
| Eric | 活泼、略带沙哑的成都男声 | 中文（四川方言） |
| Ryan | 富有节奏感的动态男声 | 英文 |
| Aiden | 阳光、清晰的美式男声 | 英文 |
| Ono_Anna | 活泼、轻快的日本女声 | 日文 |
| Sohee | 温暖、富有情感的韩国女声 | 韩文 |

## 声音设计

使用VoiceDesign模型，可以通过自然语言描述来设计声音：

```python
# 示例：设计一个撒娇的萝莉女声
instruct = "体现撒娇稚嫩的萝莉女声，音调偏高且起伏明显，营造出黏人、做作又刻意卖萌的听觉效果。"
```

## 声音克隆

使用Base模型，可以通过参考音频克隆声音：

```python
# 示例：克隆一个声音
ref_audio = "reference.wav"
ref_text = "这是参考文本"
```

## 注意事项

1. 首次启动时会自动下载模型，可能需要较长时间
2. 确保有足够的GPU内存
3. 建议使用FlashAttention 2以提高性能
4. 修改配置文件后需要重启服务或调用 `/api/config/reload` 接口

## 许可证

本项目采用 Apache-2.0 许可证
