import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """配置管理类"""
    
    _instance = None
    
    def __new__(cls, config_path: str = "config.json"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_path: str = "config.json"):
        if self._initialized:
            return
        
        self.config_path = config_path
        self._config = self._load_config()
        self._initialized = True
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
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
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def get_model_name(self, model_type: str) -> str:
        """获取模型名称"""
        model_name = self.get(f"models.{model_type}.name", "")
        model_size = self.get("model_size", "1.7B")
        return model_name.format(model_size=model_size)
    
    def save(self):
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    def reload(self):
        """重新加载配置"""
        self._config = self._load_config()
    
    @property
    def config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self._config.copy()


# 全局配置实例
config = Config()