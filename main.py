from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import json
import time
from typing import List, Optional, Any

from src.database import db, Voice
from src.text_parser import parse_novel_text
from src.audio_generator import get_audio_generator, save_audio
from src.audio_service import (
    parse_and_assign_voices, generate_project_all, generate_line_audio,
    merge_project_audio, get_inference_kwargs, build_instruct,
    is_consistency_enabled, warmup_project_voices, NARRATOR_NAME
)
from src.voice_consistency import consistency_manager
from src.config_manager import config
from src.logger import setup_logger, log_system_info

logger = setup_logger(
    name="novel_tts",
    log_level="INFO",
    log_file="logs/novel_tts.log",
    console_output=True,
    file_output=True,
)
log_system_info()

app = FastAPI(title="小说多角色语音合成系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/audio", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


def voice_to_dict(v) -> dict:
    type_labels = {"predefined": "预置", "design": "设计", "clone": "克隆"}
    return {
        "id": v.id,
        "name": v.name,
        "type": v.voice_type,
        "type_label": type_labels.get(v.voice_type, v.voice_type),
        "description": v.description or "",
        "speaker": v.speaker,
        "instruct": v.instruct or "",
        "emotion": v.emotion or "",
        "ref_text": v.ref_text or "",
        "has_ref_audio": bool(v.ref_audio_path and os.path.exists(v.ref_audio_path or "")),
        "created_at": v.created_at,
    }


# ========== 项目 API ==========

@app.post("/api/projects")
async def create_project(name: str = Form(...), text_content: str = Form(...)):
    try:
        project_id = db.create_project(name, text_content)
        return {"id": project_id, "name": name, "status": "pending"}
    except Exception as e:
        logger.error(f"创建项目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/upload")
async def create_project_from_file(name: str = Form(...), file: UploadFile = File(...)):
    """从文本文件创建项目"""
    try:
        raw = await file.read()
        for enc in ("utf-8", "gbk", "gb2312", "utf-16"):
            try:
                text_content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text_content = raw.decode("utf-8", errors="replace")
        project_id = db.create_project(name, text_content)
        return {"id": project_id, "name": name, "status": "pending", "text_length": len(text_content)}
    except Exception as e:
        logger.error(f"上传创建项目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects")
async def get_projects():
    try:
        projects = db.get_all_projects()
        return [{"id": p.id, "name": p.name, "status": p.status, "created_at": p.created_at} for p in projects]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "id": project.id, "name": project.name, "status": project.status,
        "text_content": project.text_content,
    }


@app.put("/api/projects/{project_id}/text")
async def update_project_text(project_id: int, text_content: str = Form(...)):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE projects SET text_content = ?, updated_at = datetime('now') WHERE id = ?",
        (text_content, project_id),
    )
    conn.commit()
    if not db._shared_memory:
        conn.close()
    return {"message": "文本已更新"}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    db.delete_project(project_id)
    return {"message": "项目已删除"}


@app.post("/api/projects/{project_id}/warmup-voices")
async def warmup_project_voices_api(project_id: int):
    """预热项目中所有设计/克隆声音的音色缓存"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        generator = get_audio_generator()
        warmup_project_voices(project_id, generator)
        return {"message": "项目音色预热完成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/parse")
async def parse_project_text(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        result = parse_and_assign_voices(project_id, project.text_content)
        return {"message": "文本解析完成", **result}
    except Exception as e:
        logger.error(f"解析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/workspace")
async def get_project_workspace(project_id: int):
    """项目工作台：角色、台词、音频状态"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    characters = db.get_project_characters(project_id)
    lines = db.get_project_lines(project_id)
    char_map = {c.id: c for c in characters}
    char_name = {c.id: c.name for c in characters}

    result_lines = []
    for line in lines:
        seg = db.get_audio_segment_by_line(line.id)
        char = char_map.get(line.character_id)
        voice = db.get_voice(char.voice_id) if char and char.voice_id else None
        result_lines.append({
            "id": line.id,
            "order": line.order,
            "content": line.content,
            "emotion": line.emotion or "",
            "character_id": line.character_id,
            "character_name": char_name.get(line.character_id, NARRATOR_NAME),
            "voice_id": char.voice_id if char else None,
            "voice_name": voice.name if voice else None,
            "has_audio": seg is not None,
            "audio_path": ("/" + seg.audio_path if seg and not seg.audio_path.startswith("/") else seg.audio_path) if seg else None,
            "duration": seg.duration if seg else None,
            "status": "done" if seg else "pending",
        })

    result_chars = []
    for char in characters:
        voice = db.get_voice(char.voice_id) if char.voice_id else None
        result_chars.append({
            "id": char.id,
            "name": char.name,
            "voice_id": char.voice_id,
            "voice_name": voice.name if voice else None,
            "description": char.description or "",
        })

    return {
        "project": {"id": project.id, "name": project.name, "status": project.status},
        "characters": result_chars,
        "lines": result_lines,
    }


# ========== 角色 API ==========

@app.get("/api/projects/{project_id}/characters")
async def get_characters(project_id: int):
    characters = db.get_project_characters(project_id)
    result = []
    for char in characters:
        voice = db.get_voice(char.voice_id) if char.voice_id else None
        result.append({
            "id": char.id, "name": char.name,
            "voice_id": char.voice_id,
            "voice_name": voice.name if voice else None,
            "description": char.description,
        })
    return result


@app.put("/api/projects/{project_id}/characters/{character_id}")
async def update_character(
    project_id: int,
    character_id: int,
    voice_id: int = Form(...),
    description: Optional[str] = Form(None),
):
    db.update_character_voice(character_id, voice_id)
    if description is not None:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE characters SET description = ? WHERE id = ?", (description, character_id))
        conn.commit()
        if not db._shared_memory:
            conn.close()
    return {"message": "角色已更新"}


# ========== 台词 API ==========

@app.put("/api/projects/{project_id}/lines/{line_id}/emotion")
async def update_line_emotion(project_id: int, line_id: int, emotion: str = Form("")):
    line = db.get_line(line_id)
    if not line or line.project_id != project_id:
        raise HTTPException(status_code=404, detail="台词不存在")
    db.update_line_emotion(line_id, emotion or None)
    return {"message": "情感已更新"}


@app.post("/api/projects/{project_id}/lines/{line_id}/generate")
async def generate_single_line(project_id: int, line_id: int):
    """单条台词生成/重新生成"""
    line = db.get_line(line_id)
    if not line or line.project_id != project_id:
        raise HTTPException(status_code=404, detail="台词不存在")

    characters = db.get_project_characters(project_id)
    character_map = {c.id: c for c in characters}
    path, err = generate_line_audio(project_id, line, character_map)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {
        "audio_path": "/" + path if not path.startswith("/") else path,
        "message": "生成成功",
    }


# ========== 声音库 API ==========

@app.get("/api/voices")
async def get_voices():
    return [voice_to_dict(v) for v in db.get_all_voices()]


@app.put("/api/voices/{voice_id}")
async def update_voice(
    voice_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    instruct: Optional[str] = Form(None),
    emotion: Optional[str] = Form(None),
):
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="声音不存在")
    fields = {}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    if instruct is not None:
        fields["instruct"] = instruct
    if emotion is not None:
        fields["emotion"] = emotion
    db.update_voice(voice_id, **fields)
    if fields:
        consistency_manager.invalidate(voice_id)
    return {"message": "声音已更新，音色缓存已清除"}


@app.post("/api/voices/design")
async def create_design_voice(
    name: str = Form(...),
    description: str = Form(""),
    instruct: str = Form(...),
    emotion: str = Form(""),
):
    voice = Voice(
        id=None, name=name, voice_type="design",
        description=description, instruct=instruct, emotion=emotion or None,
        created_at="",
    )
    voice_id = db.create_voice(voice)
    return {"id": voice_id, "name": name, "type": "design"}


@app.post("/api/voices/clone")
async def create_clone_voice(
    name: str = Form(...),
    description: str = Form(""),
    ref_text: str = Form(...),
    emotion: str = Form(""),
    ref_audio: UploadFile = File(...),
):
    safe_name = f"{int(time.time())}_{ref_audio.filename}"
    audio_path = f"static/uploads/{safe_name}"
    with open(audio_path, "wb") as f:
        shutil.copyfileobj(ref_audio.file, f)
    voice = Voice(
        id=None, name=name, voice_type="clone",
        description=description, ref_audio_path=audio_path,
        ref_text=ref_text, emotion=emotion or None, created_at="",
    )
    voice_id = db.create_voice(voice)
    return {"id": voice_id, "name": name, "type": "clone"}


@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: int):
    voice = db.get_voice(voice_id)
    if voice and voice.voice_type == "predefined":
        raise HTTPException(status_code=400, detail="不能删除预置声音")
    db.delete_voice(voice_id)
    consistency_manager.invalidate(voice_id)
    return {"message": "声音已删除"}


@app.post("/api/voices/{voice_id}/warmup")
async def warmup_voice(voice_id: int):
    """预生成音色锚点与克隆 prompt，提升同角色一致性"""
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="声音不存在")
    if voice.voice_type == "predefined":
        return {"message": "预置声音无需预热", "cached": False}
    try:
        generator = get_audio_generator()
        return consistency_manager.warmup_voice(voice, generator)
    except Exception as e:
        logger.error(f"预热失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/voices/{voice_id}/preview")
async def preview_voice(
    voice_id: int,
    text: str = Form("你好，这是一个声音试听。"),
    emotion: str = Form(""),
):
    voice = db.get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="声音不存在")

    generator = get_audio_generator()
    inference_kw = get_inference_kwargs()
    instruct = build_instruct(voice, emotion or None)

    try:
        if is_consistency_enabled() and voice.voice_type in ("design", "clone"):
            prompt = consistency_manager.ensure_clone_prompt(voice, generator)
            audio, sr = generator.generate_voice_clone_with_prompt(
                text=text, voice_clone_prompt=prompt,
                language=config.get("language", "Chinese"), **inference_kw,
            )
        elif voice.voice_type == "predefined":
            audio, sr = generator.generate_custom_voice(
                text=text, speaker=voice.speaker,
                language=config.get("language", "Chinese"),
                instruct=instruct or None, **inference_kw,
            )
        elif voice.voice_type == "design":
            audio, sr = generator.generate_voice_design(
                text=text,
                instruct=instruct or voice.instruct or "",
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        else:
            audio, sr = generator.generate_voice_clone(
                text=text, ref_audio_path=voice.ref_audio_path,
                ref_text=voice.ref_text,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        output_path = f"static/audio/preview_{voice_id}_{int(time.time())}.wav"
        save_audio(audio, sr, output_path)
        return {"audio_path": "/" + output_path}
    except Exception as e:
        logger.error(f"试听失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 音频生成 API ==========

@app.post("/api/projects/{project_id}/generate")
async def generate_project_audio(project_id: int):
    """服务端批量生成（同步阻塞，适合 API 调用；前端一键生成请用逐条接口）"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        result = generate_project_all(project_id)
        return {"message": "批量生成完成", **result}
    except Exception as e:
        logger.error(f"批量生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/merge")
async def merge_project_audio_api(project_id: int):
    """合并已生成的台词音频"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    path = merge_project_audio(project_id)
    if not path:
        raise HTTPException(status_code=400, detail="没有可合并的音频片段")
    db.update_project_status(project_id, "completed")
    return {"message": "合并完成", "audio_path": "/" + path}


@app.get("/api/projects/{project_id}/audio")
async def get_project_audio(project_id: int):
    segments = db.get_project_audio_segments(project_id)
    return [
        {"id": s.id, "line_id": s.line_id, "character_id": s.character_id,
         "audio_path": "/" + s.audio_path if not s.audio_path.startswith("/") else s.audio_path,
         "duration": s.duration}
        for s in segments
    ]


@app.get("/api/projects/{project_id}/download")
async def download_project_audio(project_id: int):
    audio_path = f"static/audio/project_{project_id}_merged.wav"
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="合并音频不存在，请先生成")
    return FileResponse(audio_path, filename=f"project_{project_id}_audio.wav")


# ========== 配置 API ==========

INFERENCE_KEYS = ("temperature", "top_p", "top_k", "repetition_penalty", "max_new_tokens", "language")
CONSISTENCY_KEYS = (
    "enabled", "design_via_clone", "stable_instruct", "line_emotion_affects_timbre",
    "temperature", "top_p", "top_k", "repetition_penalty", "x_vector_only_mode", "anchor_text",
)


@app.get("/api/config")
async def get_config_api():
    cfg = config.config.copy()
    cfg["inference"] = {k: config.get(k) for k in INFERENCE_KEYS}
    cfg["consistency"] = {k: config.get(f"consistency.{k}") for k in CONSISTENCY_KEYS}
    return cfg


@app.put("/api/config/inference")
async def update_inference_config(body: dict = Body(...)):
    """更新推理参数并持久化"""
    for key in INFERENCE_KEYS:
        if key in body:
            config.set(key, body[key])
    if "consistency" in body and isinstance(body["consistency"], dict):
        for k, v in body["consistency"].items():
            if k in CONSISTENCY_KEYS:
                config.set(f"consistency.{k}", v)
    if "audio" in body and isinstance(body["audio"], dict):
        for k, v in body["audio"].items():
            config.set(f"audio.{k}", v)
    config.save()
    return {
        "message": "推理参数已保存",
        "inference": {k: config.get(k) for k in INFERENCE_KEYS},
        "consistency": {k: config.get(f"consistency.{k}") for k in CONSISTENCY_KEYS},
    }


@app.post("/api/config/reload")
async def reload_config():
    config.reload()
    return {"message": "配置已重新加载"}


@app.get("/api/logs")
async def get_logs(lines: int = 100):
    log_file = "logs/novel_tts.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            return {"logs": f.readlines()[-lines:]}
    return {"logs": []}


@app.get("/novel_example.txt")
async def novel_example_file():
    path = Path("novel_example.txt")
    if path.exists():
        return FileResponse(path, media_type="text/plain; charset=utf-8")
    raise HTTPException(status_code=404, detail="示例文件不存在")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    index = Path("static/index.html")
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>请将 static/index.html 放到项目中</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
