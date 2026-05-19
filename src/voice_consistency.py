"""角色声音一致性：缓存克隆 prompt、设计音锚点复用"""
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

from .config_manager import config
from .database import Voice, db
from .logger import LoggerMixin

PROMPT_DIR = Path("static/voice_prompts")
ANCHOR_DIR = Path("static/voice_anchors")


class VoiceConsistencyManager(LoggerMixin):
    """按 voice_id 缓存 VoiceClonePromptItem，保证同角色音色稳定"""

    def __init__(self):
        super().__init__()
        self._memory: Dict[int, list] = {}
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        ANCHOR_DIR.mkdir(parents=True, exist_ok=True)

    def _prompt_path(self, voice_id: int) -> Path:
        return PROMPT_DIR / f"voice_{voice_id}.pt"

    def _save_prompt(self, voice_id: int, items: list) -> None:
        payload = {"items": [asdict(it) for it in items]}
        torch.save(payload, self._prompt_path(voice_id))

    def _load_prompt(self, voice_id: int) -> Optional[list]:
        path = self._prompt_path(voice_id)
        if not path.exists():
            return None
        try:
            from qwen_tts import VoiceClonePromptItem

            payload = torch.load(path, map_location="cpu", weights_only=True)
            items = []
            for d in payload.get("items", []):
                ref_code = d.get("ref_code")
                if ref_code is not None and not torch.is_tensor(ref_code):
                    ref_code = torch.tensor(ref_code)
                ref_spk = d.get("ref_spk_embedding")
                if ref_spk is None:
                    continue
                if not torch.is_tensor(ref_spk):
                    ref_spk = torch.tensor(ref_spk)
                items.append(
                    VoiceClonePromptItem(
                        ref_code=ref_code,
                        ref_spk_embedding=ref_spk,
                        x_vector_only_mode=bool(d.get("x_vector_only_mode", False)),
                        icl_mode=bool(d.get("icl_mode", True)),
                        ref_text=d.get("ref_text"),
                    )
                )
            return items if items else None
        except Exception as e:
            self.logger.warning(f"加载音色缓存失败 voice_id={voice_id}: {e}")
            return None

    def get_prompt(self, voice_id: int) -> Optional[list]:
        if voice_id in self._memory:
            return self._memory[voice_id]
        items = self._load_prompt(voice_id)
        if items:
            self._memory[voice_id] = items
        return items

    def set_prompt(self, voice_id: int, items: list) -> None:
        self._memory[voice_id] = items
        self._save_prompt(voice_id, items)

    def ensure_clone_prompt(self, voice: Voice, generator) -> list:
        """为 clone / design 声音获取或构建可复用的克隆 prompt"""
        if voice.id is None:
            raise ValueError("voice.id 不能为空")

        cached = self.get_prompt(voice.id)
        if cached:
            return cached

        if voice.voice_type == "clone":
            items = self._prompt_from_ref_audio(generator, voice.ref_audio_path, voice.ref_text)
            self.set_prompt(voice.id, items)
            return items

        if voice.voice_type == "design" and config.get("consistency.design_via_clone", True):
            anchor_path, anchor_text = self._ensure_design_anchor(voice, generator)
            items = self._prompt_from_ref_audio(generator, anchor_path, anchor_text)
            self.set_prompt(voice.id, items)
            return items

        raise ValueError(f"无法为类型 {voice.voice_type} 构建克隆 prompt")

    def _prompt_from_ref_audio(self, generator, ref_audio_path: str, ref_text: str) -> list:
        if not ref_audio_path or not os.path.exists(ref_audio_path):
            raise FileNotFoundError(f"参考音频不存在: {ref_audio_path}")
        xvec = config.get("consistency.x_vector_only_mode", False)
        ref_text = ref_text or config.get(
            "consistency.anchor_text",
            "你好，我是这个角色，很高兴为你朗读这段小说。",
        )
        return generator.voice_clone_model.create_voice_clone_prompt(
            ref_audio=ref_audio_path,
            ref_text=ref_text if not xvec else None,
            x_vector_only_mode=xvec,
        )

    def _ensure_design_anchor(self, voice: Voice, generator) -> Tuple[str, str]:
        """用 VoiceDesign 生成一次锚点音频，后续全部走克隆复用"""
        anchor_path = voice.ref_audio_path if voice.ref_audio_path and os.path.exists(voice.ref_audio_path) else None
        anchor_text = voice.ref_text

        default_anchor = str(ANCHOR_DIR / f"voice_{voice.id}_anchor.wav")
        if os.path.exists(default_anchor):
            anchor_path = default_anchor
            anchor_text = voice.ref_text or config.get(
                "consistency.anchor_text",
                "你好，我是这个角色，很高兴为你朗读这段小说。",
            )
            db.update_voice(voice.id, ref_audio_path=anchor_path, ref_text=anchor_text)
            return anchor_path, anchor_text

        if anchor_path and anchor_text:
            return anchor_path, anchor_text

        anchor_text = config.get(
            "consistency.anchor_text",
            "你好，我是这个角色，很高兴为你朗读这段小说。",
        )
        instruct = (voice.instruct or "").strip()
        if voice.emotion:
            emotion = voice.emotion.strip()
            instruct = f"{instruct}，{emotion}" if instruct else emotion

        self.logger.info(f"为设计声音 [{voice.name}] 生成锚点参考音频…")
        wav, sr = generator.generate_voice_design(
            text=anchor_text,
            instruct=instruct or "自然清晰的中文朗读声，语速适中，音色稳定",
            language=config.get("language", "Chinese"),
            **self._consistency_gen_kwargs(),
        )

        out_path = str(ANCHOR_DIR / f"voice_{voice.id}_anchor.wav")
        import soundfile as sf
        sf.write(out_path, wav, sr)

        db.update_voice(voice.id, ref_audio_path=out_path, ref_text=anchor_text)
        voice.ref_audio_path = out_path
        voice.ref_text = anchor_text
        self.logger.info(f"锚点已保存: {out_path}")
        return out_path, anchor_text

    def _consistency_gen_kwargs(self) -> dict:
        return {
            "temperature": config.get("consistency.temperature", 0.65),
            "top_p": config.get("consistency.top_p", 0.9),
            "top_k": config.get("consistency.top_k", 40),
            "repetition_penalty": config.get("consistency.repetition_penalty", 1.05),
        }

    def warmup_voice(self, voice: Voice, generator) -> dict:
        """预构建音色缓存（可在绑定角色后手动触发）"""
        if voice.voice_type == "predefined":
            return {"message": "预置声音无需预热", "cached": False}
        items = self.ensure_clone_prompt(voice, generator)
        return {"message": "音色缓存已就绪", "cached": True, "prompt_items": len(items)}

    def invalidate(self, voice_id: int) -> None:
        self._memory.pop(voice_id, None)
        path = self._prompt_path(voice_id)
        if path.exists():
            path.unlink()


consistency_manager = VoiceConsistencyManager()
