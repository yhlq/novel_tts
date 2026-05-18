import os
import sys
import json
import tempfile
import time
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# 添加Qwen3-TTS路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'qwen3-tts-usages', 'Qwen3-TTS'))

from qwen_tts import Qwen3TTSModel
from .config_manager import config
from .logger import LoggerMixin, log_time, log_execution_time, log_model_info, log_generation_info


@dataclass
class VoiceConfig:
    """声音配置"""
    id: int
    name: str
    voice_type: str  # predefined/design/clone
    speaker: Optional[str] = None
    instruct: Optional[str] = None
    ref_audio_path: Optional[str] = None
    ref_text: Optional[str] = None
    emotion: Optional[str] = None


class AudioGenerator(LoggerMixin):
    """音频生成器"""
    
    def __init__(self, device: str = None, model_size: str = None):
        """
        初始化音频生成器
        
        Args:
            device: 设备，如 "cuda:0" 或 "cpu"，默认从配置文件读取
            model_size: 模型大小，"0.6B" 或 "1.7B"，默认从配置文件读取
        """
        super().__init__()
        
        # 从配置文件读取参数
        self.device = device or config.get("device", "cuda:0")
        self.model_size = model_size or config.get("model_size", "1.7B")
        self.dtype = config.get("dtype", "bfloat16")
        self.attn_implementation = config.get("attn_implementation", "flash_attention_2")
        
        self.custom_voice_model = None
        self.voice_design_model = None
        self.voice_clone_model = None
        
        self.logger.info(f"初始化 AudioGenerator，设备: {self.device}, 模型大小: {self.model_size}")
        
        self._load_models()
    
    def _load_models(self):
        """加载Qwen3-TTS模型"""
        import torch
        
        # 从配置文件获取模型名称
        custom_voice_name = config.get_model_name("custom_voice")
        voice_design_name = config.get_model_name("voice_design")
        base_name = config.get_model_name("base")
        
        # 数据类型映射
        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32
        }
        dtype = dtype_map.get(self.dtype, torch.bfloat16)
        
        # 加载CustomVoice模型
        self.logger.info(f"加载 CustomVoice 模型 ({custom_voice_name})...")
        start_time = time.time()
        try:
            self.custom_voice_model = Qwen3TTSModel.from_pretrained(
                custom_voice_name,
                device_map=self.device,
                dtype=dtype,
                attn_implementation=self.attn_implementation,
            )
            load_time = time.time() - start_time
            self.logger.info(f"CustomVoice 模型加载完成，耗时: {load_time:.2f} 秒")
            log_model_info(custom_voice_name, self.device, self.dtype)
        except Exception as e:
            self.log_error("CustomVoice 模型加载失败", e)
            raise
        
        # 加载VoiceDesign模型
        self.logger.info(f"加载 VoiceDesign 模型 ({voice_design_name})...")
        start_time = time.time()
        try:
            self.voice_design_model = Qwen3TTSModel.from_pretrained(
                voice_design_name,
                device_map=self.device,
                dtype=dtype,
                attn_implementation=self.attn_implementation,
            )
            load_time = time.time() - start_time
            self.logger.info(f"VoiceDesign 模型加载完成，耗时: {load_time:.2f} 秒")
            log_model_info(voice_design_name, self.device, self.dtype)
        except Exception as e:
            self.log_error("VoiceDesign 模型加载失败", e)
            raise
        
        # 加载Base模型（用于克隆）
        self.logger.info(f"加载 Base 模型 ({base_name})...")
        start_time = time.time()
        try:
            self.voice_clone_model = Qwen3TTSModel.from_pretrained(
                base_name,
                device_map=self.device,
                dtype=dtype,
                attn_implementation=self.attn_implementation,
            )
            load_time = time.time() - start_time
            self.logger.info(f"Base 模型加载完成，耗时: {load_time:.2f} 秒")
            log_model_info(base_name, self.device, self.dtype)
        except Exception as e:
            self.log_error("Base 模型加载失败", e)
            raise
        
        self.logger.info("所有模型加载完成！")
    
    def _inference_kwargs(self, kwargs: dict) -> dict:
        defaults = {
            "temperature": config.get("temperature", 0.9),
            "top_p": config.get("top_p", 1.0),
            "top_k": config.get("top_k", 50),
            "repetition_penalty": config.get("repetition_penalty", 1.05),
            "max_new_tokens": config.get("max_new_tokens", 2048),
        }
        defaults.update({k: v for k, v in kwargs.items() if v is not None})
        return defaults

    def generate_custom_voice(self, text: str, speaker: str, language: str = None, instruct: str = "", **kwargs) -> Tuple[np.ndarray, int]:
        """
        使用预置声音生成音频
        
        Args:
            text: 要合成的文本
            speaker: 预置声音名称
            language: 语言，默认从配置文件读取
            instruct: 指令（可选）
            
        Returns:
            Tuple[np.ndarray, int]: (音频数据, 采样率)
        """
        language = language or config.get("language", "Chinese")
        
        if not instruct:
            instruct = None
        
        self.logger.info(f"生成预置声音音频: speaker={speaker}, language={language}, text_length={len(text)}")
        start_time = time.time()
        
        try:
            gen_kw = self._inference_kwargs(kwargs)
            wavs, sr = self.custom_voice_model.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker,
                instruct=instruct,
                **gen_kw,
            )
            
            generation_time = time.time() - start_time
            self.logger.info(f"预置声音音频生成完成，耗时: {generation_time:.2f} 秒")
            log_generation_info(text, speaker, language)
            
            return wavs[0], sr
        except Exception as e:
            self.log_error("预置声音音频生成失败", e)
            raise
    
    def generate_voice_design(self, text: str, instruct: str, language: str = None, **kwargs) -> Tuple[np.ndarray, int]:
        """
        使用声音设计生成音频
        
        Args:
            text: 要合成的文本
            instruct: 声音设计描述
            language: 语言，默认从配置文件读取
            
        Returns:
            Tuple[np.ndarray, int]: (音频数据, 采样率)
        """
        language = language or config.get("language", "Chinese")
        
        self.logger.info(f"生成设计声音音频: instruct={instruct[:50]}..., language={language}, text_length={len(text)}")
        start_time = time.time()
        
        try:
            gen_kw = self._inference_kwargs(kwargs)
            wavs, sr = self.voice_design_model.generate_voice_design(
                text=text,
                language=language,
                instruct=instruct,
                **gen_kw,
            )
            
            generation_time = time.time() - start_time
            self.logger.info(f"设计声音音频生成完成，耗时: {generation_time:.2f} 秒")
            log_generation_info(text, language=language)
            
            return wavs[0], sr
        except Exception as e:
            self.log_error("设计声音音频生成失败", e)
            raise
    
    def generate_voice_clone(self, text: str, ref_audio_path: str, ref_text: str, language: str = None, **kwargs) -> Tuple[np.ndarray, int]:
        """
        使用声音克隆生成音频
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            ref_text: 参考文本
            language: 语言，默认从配置文件读取
            
        Returns:
            Tuple[np.ndarray, int]: (音频数据, 采样率)
        """
        language = language or config.get("language", "Chinese")
        
        self.logger.info(f"生成克隆声音音频: ref_audio={ref_audio_path}, language={language}, text_length={len(text)}")
        start_time = time.time()
        
        try:
            gen_kw = self._inference_kwargs(kwargs)
            wavs, sr = self.voice_clone_model.generate_voice_clone(
                text=text,
                language=language,
                ref_audio=ref_audio_path,
                ref_text=ref_text,
                **gen_kw,
            )
            
            generation_time = time.time() - start_time
            self.logger.info(f"克隆声音音频生成完成，耗时: {generation_time:.2f} 秒")
            log_generation_info(text, language=language)
            
            return wavs[0], sr
        except Exception as e:
            self.log_error("克隆声音音频生成失败", e)
            raise
    
    def create_voice_clone_prompt(self, ref_audio_path: str, ref_text: str):
        """
        创建声音克隆提示
        
        Args:
            ref_audio_path: 参考音频路径
            ref_text: 参考文本
            
        Returns:
            VoiceClonePromptItem: 声音克隆提示
        """
        self.logger.info(f"创建声音克隆提示: ref_audio={ref_audio_path}")
        
        try:
            return self.voice_clone_model.create_voice_clone_prompt(
                ref_audio=ref_audio_path,
                ref_text=ref_text,
            )
        except Exception as e:
            self.log_error("创建声音克隆提示失败", e)
            raise
    
    def generate_with_voice_config(self, text: str, voice_config: VoiceConfig, language: str = None) -> Tuple[np.ndarray, int]:
        """
        根据声音配置生成音频
        
        Args:
            text: 要合成的文本
            voice_config: 声音配置
            language: 语言，默认从配置文件读取
            
        Returns:
            Tuple[np.ndarray, int]: (音频数据, 采样率)
        """
        language = language or config.get("language", "Chinese")
        
        self.logger.info(f"根据声音配置生成音频: voice_type={voice_config.voice_type}, text_length={len(text)}")
        
        if voice_config.voice_type == "predefined":
            return self.generate_custom_voice(
                text=text,
                speaker=voice_config.speaker,
                language=language,
                instruct=voice_config.instruct or ""
            )
        elif voice_config.voice_type == "design":
            return self.generate_voice_design(
                text=text,
                instruct=voice_config.instruct,
                language=language
            )
        elif voice_config.voice_type == "clone":
            return self.generate_voice_clone(
                text=text,
                ref_audio_path=voice_config.ref_audio_path,
                ref_text=voice_config.ref_text,
                language=language
            )
        else:
            error_msg = f"未知的声音类型: {voice_config.voice_type}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)
    
    def generate_batch(self, texts: List[str], voice_configs: List[VoiceConfig], language: str = None) -> List[Tuple[np.ndarray, int]]:
        """
        批量生成音频
        
        Args:
            texts: 要合成的文本列表
            voice_configs: 声音配置列表
            language: 语言，默认从配置文件读取
            
        Returns:
            List[Tuple[np.ndarray, int]]: (音频数据, 采样率)列表
        """
        language = language or config.get("language", "Chinese")
        
        self.logger.info(f"批量生成音频: 共 {len(texts)} 条")
        start_time = time.time()
        
        results = []
        for i, (text, voice_config) in enumerate(zip(texts, voice_configs)):
            try:
                self.logger.debug(f"生成第 {i+1}/{len(texts)} 条音频")
                audio, sr = self.generate_with_voice_config(text, voice_config, language)
                results.append((audio, sr))
            except Exception as e:
                self.log_error(f"第 {i+1} 条音频生成失败", e)
                results.append((None, None))
        
        total_time = time.time() - start_time
        self.logger.info(f"批量生成完成，成功 {sum(1 for r in results if r[0] is not None)}/{len(texts)} 条，耗时: {total_time:.2f} 秒")
        
        return results


def merge_audio_segments(audio_segments: List[Tuple[np.ndarray, int]], output_path: str, pause_duration: float = None):
    """
    合并音频片段
    
    Args:
        audio_segments: 音频片段列表，每个元素为 (音频数据, 采样率)
        output_path: 输出文件路径
        pause_duration: 片段之间的停顿时间（秒），默认从配置文件读取
    """
    if not audio_segments:
        return
    
    # 获取配置
    pause_duration = pause_duration or config.get("audio.pause_duration", 0.5)
    
    # 获取采样率
    sr = audio_segments[0][1]
    
    # 创建停顿音频
    pause_samples = int(sr * pause_duration)
    pause_audio = np.zeros(pause_samples, dtype=np.float32)
    
    # 合并所有音频
    merged_audio = []
    for i, (audio, _) in enumerate(audio_segments):
        if audio is not None:
            merged_audio.append(audio)
            # 添加停顿（最后一个片段后不添加）
            if i < len(audio_segments) - 1:
                merged_audio.append(pause_audio)
    
    # 合并为单个数组
    if merged_audio:
        final_audio = np.concatenate(merged_audio)
        sf.write(output_path, final_audio, sr)


def save_audio(audio: np.ndarray, sr: int, output_path: str):
    """
    保存音频文件
    
    Args:
        audio: 音频数据
        sr: 采样率
        output_path: 输出路径
    """
    sf.write(output_path, audio, sr)


# 全局音频生成器实例
audio_generator = None


def get_audio_generator() -> AudioGenerator:
    """获取音频生成器实例"""
    global audio_generator
    if audio_generator is None:
        audio_generator = AudioGenerator()
    return audio_generator