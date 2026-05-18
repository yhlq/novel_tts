"""音频生成业务逻辑"""
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from .database import db, Character, Line, Voice
from .audio_generator import (
    AudioGenerator, get_audio_generator,
    merge_audio_segments, save_audio
)
from .config_manager import config
from .voice_consistency import consistency_manager


NARRATOR_NAME = "旁白"


def is_consistency_enabled() -> bool:
    return config.get("consistency.enabled", True)


def get_inference_kwargs() -> dict:
    """从配置读取模型推理参数；一致性模式下使用更稳定的采样参数"""
    if is_consistency_enabled():
        return {
            "temperature": config.get("consistency.temperature", config.get("temperature", 0.65)),
            "top_p": config.get("consistency.top_p", config.get("top_p", 0.9)),
            "top_k": config.get("consistency.top_k", config.get("top_k", 40)),
            "repetition_penalty": config.get(
                "consistency.repetition_penalty", config.get("repetition_penalty", 1.05)
            ),
            "max_new_tokens": config.get("max_new_tokens", 2048),
        }
    return {
        "temperature": config.get("temperature", 0.9),
        "top_p": config.get("top_p", 1.0),
        "top_k": config.get("top_k", 50),
        "repetition_penalty": config.get("repetition_penalty", 1.05),
        "max_new_tokens": config.get("max_new_tokens", 2048),
    }


def build_instruct(voice: Voice, line_emotion: Optional[str] = None) -> Optional[str]:
    """
    构建 instruct。一致性模式下默认只用声音级描述，避免每句情感导致音色漂移。
    """
    stable = is_consistency_enabled() and config.get("consistency.stable_instruct", True)
    allow_line_emotion = config.get("consistency.line_emotion_affects_timbre", False)

    parts = []
    if voice.voice_type == "design" and voice.instruct:
        parts.append(voice.instruct.strip())
    if voice.emotion:
        parts.append(voice.emotion.strip())
    if not stable and allow_line_emotion and line_emotion and line_emotion.strip():
        parts.append(line_emotion.strip())

    if voice.voice_type == "predefined":
        if not parts:
            return None
        return "，".join(parts)

    return "，".join(parts) if parts else None


def warmup_project_voices(project_id: int, generator: Optional[AudioGenerator] = None) -> None:
    """批量生成前预热项目中用到的所有声音缓存"""
    gen = generator or get_audio_generator()
    if not is_consistency_enabled():
        return
    characters = db.get_project_characters(project_id)
    voice_ids = {c.voice_id for c in characters if c.voice_id}
    for vid in voice_ids:
        voice = db.get_voice(vid)
        if voice and voice.voice_type in ("design", "clone"):
            try:
                consistency_manager.ensure_clone_prompt(voice, gen)
            except Exception as e:
                gen.logger.warning(f"预热声音失败 voice_id={vid}: {e}")


def generate_line_audio(
    project_id: int,
    line: Line,
    character_map: Dict[int, Character],
    generator: Optional[AudioGenerator] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    为单条台词生成音频。
    返回 (audio_path, error_message)
    """
    gen = generator or get_audio_generator()
    inference_kw = get_inference_kwargs()

    char = character_map.get(line.character_id) if line.character_id else None
    if not char or not char.voice_id:
        return None, "角色未绑定声音"

    voice = db.get_voice(char.voice_id)
    if not voice:
        return None, "声音不存在"

    try:
        if is_consistency_enabled() and voice.voice_type in ("design", "clone"):
            prompt = consistency_manager.ensure_clone_prompt(voice, gen)
            audio, sr = gen.generate_voice_clone_with_prompt(
                text=line.content,
                voice_clone_prompt=prompt,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        elif voice.voice_type == "predefined":
            instruct = build_instruct(voice, line.emotion)
            audio, sr = gen.generate_custom_voice(
                text=line.content,
                speaker=voice.speaker,
                language=config.get("language", "Chinese"),
                instruct=instruct,
                **inference_kw,
            )
        elif voice.voice_type == "design":
            design_instruct = build_instruct(voice, line.emotion) or voice.instruct or voice.emotion or ""
            audio, sr = gen.generate_voice_design(
                text=line.content,
                instruct=design_instruct,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        elif voice.voice_type == "clone":
            audio, sr = gen.generate_voice_clone(
                text=line.content,
                ref_audio_path=voice.ref_audio_path,
                ref_text=voice.ref_text,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        else:
            return None, f"未知声音类型: {voice.voice_type}"

        output_path = f"static/audio/project_{project_id}_line_{line.id}.wav"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        save_audio(audio, sr, output_path)
        duration = len(audio) / sr
        db.upsert_audio_segment(project_id, line.id, line.character_id, output_path, duration)
        return output_path, None
    except Exception as e:
        return None, str(e)


def generate_project_all(project_id: int) -> dict:
    """批量生成项目全部台词音频并合并"""
    lines = db.get_project_lines(project_id)
    if not lines:
        return {"success": 0, "failed": 0, "errors": ["项目没有台词"]}

    characters = db.get_project_characters(project_id)
    character_map = {c.id: c for c in characters}
    generator = get_audio_generator()
    db.update_project_status(project_id, "generating")

    warmup_project_voices(project_id, generator)

    audio_segments: List[Tuple[np.ndarray, int]] = []
    errors = []
    success = 0
    failed = 0

    for line in lines:
        path, err = generate_line_audio(project_id, line, character_map, generator)
        if path:
            success += 1
            import soundfile as sf
            audio, sr = sf.read(path)
            audio_segments.append((audio, sr))
        else:
            failed += 1
            errors.append(f"第{line.order + 1}行: {err}")

    if audio_segments:
        merged_path = f"static/audio/project_{project_id}_merged.wav"
        merge_audio_segments(audio_segments, merged_path)

    db.update_project_status(project_id, "completed" if success else "parsed")
    return {"success": success, "failed": failed, "errors": errors[:20]}


def merge_project_audio(project_id: int) -> Optional[str]:
    """按台词顺序合并已生成的音频片段"""
    import soundfile as sf

    lines = db.get_project_lines(project_id)
    audio_segments: List[Tuple[np.ndarray, int]] = []
    for line in lines:
        seg = db.get_audio_segment_by_line(line.id)
        if seg and seg.audio_path and os.path.exists(seg.audio_path):
            audio, sr = sf.read(seg.audio_path)
            audio_segments.append((audio, sr))
    if not audio_segments:
        return None
    merged_path = f"static/audio/project_{project_id}_merged.wav"
    merge_audio_segments(audio_segments, merged_path)
    return merged_path


def parse_and_assign_voices(project_id: int, text_content: str) -> dict:
    """解析文本、创建角色与台词、自动分配声音"""
    from .text_parser import parse_novel_text, auto_assign_voices_to_characters

    db.clear_project_parsed_data(project_id)
    lines, characters = parse_novel_text(text_content)

    has_narration = any(l.character is None for l in lines)
    if has_narration:
        characters[NARRATOR_NAME] = characters.get(NARRATOR_NAME, 0) + sum(
            1 for l in lines if l.character is None
        )

    character_ids = {}
    for char_name in characters.keys():
        character_ids[char_name] = db.create_character(project_id, char_name)

    for line in lines:
        char_name = line.character if line.character else NARRATOR_NAME
        char_id = character_ids.get(char_name)
        db.create_line(project_id, char_id, line.content, line.order, line.emotion)

    available_voices = db.get_all_voices()
    voice_names = [v.name for v in available_voices]
    assignments = auto_assign_voices_to_characters(characters, voice_names)

    name_to_voice = {v.name: v for v in available_voices}
    for char_name, voice_name in assignments.items():
        char_id = character_ids.get(char_name)
        voice = name_to_voice.get(voice_name)
        if char_id and voice:
            db.update_character_voice(char_id, voice.id)

    db.update_project_status(project_id, "parsed")
    return {
        "characters": list(characters.keys()),
        "lines_count": len(lines),
        "assignments": assignments,
    }
