"""台本JSON → 縦型ショート動画の合成（SPEC 6章・最重要）。

レイヤ構成（下→上）:
  背景/B-roll(Ken Burns) → テンポ自動ズーム → キャラ(口パク/表情/話者拡大)
  → 字幕 → テロップ(hook/visual_keyword) → 上部ロゴ・バッジ → フラッシュ
音声は wav_path があれば配置、無ければ無音（M1はVOICEVOX無しで動く）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from moviepy import CompositeVideoClip, ImageClip
from PIL import Image

from ..shared.models import Script
from . import assets, effects, layout, textgen
from .timeline import Timeline, build_timeline, find_tempo_gaps, tempo_fill_zooms


@dataclass
class RenderResult:
    path: Path
    duration_sec: float


# ---- 小物ヘルパ -------------------------------------------------------------


def _pil_to_imageclip(img: Image.Image) -> ImageClip:
    import numpy as np

    arr = np.array(img.convert("RGBA"))
    return ImageClip(arr[:, :, :3], transparent=False).with_mask(
        ImageClip(arr[:, :, 3] / 255.0, is_mask=True)
    )


def _char_clip(img_path: Path, center_x: int, scale: float) -> ImageClip:
    ic = ImageClip(str(img_path))
    th = int(layout.CHAR_TARGET_H * scale)
    ic = ic.resized(height=th)
    w, h = ic.size
    return ic.with_position((center_x - w / 2, layout.CHAR_BOTTOM_Y - h))


def _cover_bg(img_path: Path) -> ImageClip:
    return ImageClip(str(img_path)).resized(layout.CANVAS)


# ---- レイヤ生成 -------------------------------------------------------------


def _background_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    clips: list[ImageClip] = []
    # 固定背景（全編・Ken Burns）
    bg = _cover_bg(assets.background_for_corner(script.corner))
    clips.append(effects.ken_burns(bg, tl.total).with_start(0))

    # B-roll をタイムラインに配置（各 start_line の開始時刻から次のB-rollまで）
    brolls = sorted(script.brolls, key=lambda b: b.start_line)
    starts = [tl.spans[b.start_line].start for b in brolls]
    for i, b in enumerate(brolls):
        seg_start = starts[i]
        seg_end = starts[i + 1] if i + 1 < len(starts) else tl.total
        seg_dur = max(0.1, seg_end - seg_start)
        img = Path(b.image_path) if b.image_path and Path(b.image_path).exists() else None
        if img is None:
            img = assets.layout_asset("broll_placeholder.png")
        broll = _cover_bg(img)
        clips.append(effects.ken_burns(broll, seg_dur).with_start(seg_start))
    return clips


def _tempo_autozoom_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    """無変化2.5秒超の区間に軽い背景ズームを挿入（SPEC テンポ規則）。"""
    gaps = find_tempo_gaps(tl.change_events)
    zoom_times = tempo_fill_zooms(gaps)
    clips: list[ImageClip] = []
    bg_path = assets.background_for_corner(script.corner)
    for zt in zoom_times:
        seg = _cover_bg(bg_path)
        dur = 1.2
        clips.append(
            effects.ken_burns(seg, dur, z0=1.02, z1=1.12).with_start(max(0.0, zt - dur / 2))
        )
    return clips


def _character_layers(tl: Timeline) -> list[ImageClip]:
    clips: list[ImageClip] = []
    dt = 1.0 / layout.MOUTH_FPS
    for speaker in ("fox", "rabbit"):
        cx = layout.center_x_for(speaker)
        # アイドル土台（normal・等倍・全編）
        idle = assets.emotion_image(speaker, "normal")
        clips.append(
            _char_clip(idle, cx, layout.SPEAKER_SCALE_IDLE).with_start(0).with_duration(tl.total)
        )
        # 発話区間：表情＋口パク（8fpsで mouth_open ↔ 表情フレーム）。
        # スケールは emotion 連動の登場演出（surprised=バウンス等）を tick 単位で反映。
        for span in tl.spans:
            if span.speaker != speaker:
                continue
            emo_img = assets.emotion_image(speaker, span.emotion)
            n_ticks = max(1, math.ceil(span.duration / dt))
            for k in range(n_ticks):
                ts = span.start + k * dt
                td = min(dt, span.end - ts)
                if td <= 0:
                    break
                is_open = k % 2 == 1
                img = assets.mouth_image(speaker, True) if is_open else emo_img
                scale = effects.speaker_entrance_scale(span.emotion, ts - span.start)
                clips.append(_char_clip(img, cx, scale).with_start(ts).with_duration(td))
    return clips


def _subtitle_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    clips: list[ImageClip] = []
    for span in tl.spans:
        line = script.exchanges[span.index]
        png = textgen.subtitle_png(
            line.text,
            layout.accent_for(span.speaker),
            size=layout.SUBTITLE_FONT_SIZE,
            max_width=layout.SUBTITLE_MAX_WIDTH_PX,
            max_lines=layout.SUBTITLE_MAX_LINES,
            stroke_px=layout.SUBTITLE_STROKE_PX,
            fill=layout.SUBTITLE_FILL,
            stroke=layout.SUBTITLE_STROKE,
        )
        clip = _pil_to_imageclip(png).with_duration(span.duration)
        center = (layout.WIDTH / 2, layout.SUBTITLE_CENTER_Y)
        clip = effects.subtitle_entrance(clip, center, span.emotion)
        clips.append(clip.with_start(span.start))
    return clips


def _telop_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    clips: list[ImageClip] = []
    center = (layout.WIDTH / 2, layout.TELOP_CENTER_Y)
    hook_end = min(tl.spans[0].end, 2.5)

    # hook: デカ文字ドロップ+着地シェイク（フラッシュは _accent_layers で着地に同期）
    hook_png = textgen.telop_png(
        script.hook, size=layout.HOOK_FONT_SIZE, max_width=int(layout.WIDTH * 0.9)
    )
    hook_clip = _pil_to_imageclip(hook_png).with_duration(hook_end)
    hook_clip = effects.drop_slam(hook_clip, center).with_start(0)
    clips.append(hook_clip)

    # visual_keyword: pop_in バウンス（hook後〜末尾）
    vk_png = textgen.telop_png(
        script.visual_keyword, size=layout.TELOP_FONT_SIZE, max_width=int(layout.WIDTH * 0.9)
    )
    vk_dur = max(0.5, tl.total - hook_end)
    vk_clip = _pil_to_imageclip(vk_png).with_duration(vk_dur)
    vk_clip = effects.pop_in(vk_clip, center, dur=layout.TELOP_BOUNCE_SEC).with_start(hook_end)
    clips.append(vk_clip)
    return clips


def _accent_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    """フラッシュ系のアクセント（最前面レイヤ）。

    - フックのデカ文字着地の瞬間（t=HOOK_DROP_SEC）に白フラッシュ
    - emotion=surprised のセリフ頭に控えめな小フラッシュ（感情連動）
    """
    clips: list[ImageClip] = [effects.flash(at=layout.HOOK_DROP_SEC)]
    for span in tl.spans:
        if span.emotion == "surprised" and span.start > layout.HOOK_DROP_SEC:
            clips.append(effects.flash(at=span.start, opacity=layout.SURPRISE_FLASH_OPACITY))
    return clips


def _top_layers(script: Script, tl: Timeline) -> list[ImageClip]:
    clips: list[ImageClip] = []
    logo = ImageClip(str(assets.layout_asset("logo.png"))).resized(width=int(layout.WIDTH * 0.5))
    lw, _ = logo.size
    clips.append(
        logo.with_position((layout.WIDTH / 2 - lw / 2, layout.LOGO_TOP_Y))
        .with_start(0)
        .with_duration(tl.total)
    )
    badge = assets.badge_for_corner(script.corner)
    if badge:
        bclip = ImageClip(str(badge)).resized(width=int(layout.WIDTH * 0.36))
        bw, _ = bclip.size
        clips.append(
            bclip.with_position((layout.WIDTH / 2 - bw / 2, layout.BADGE_TOP_Y))
            .with_start(0)
            .with_duration(tl.total)
        )
    return clips


# ---- 音声 -------------------------------------------------------------------


def _build_audio(script: Script, tl: Timeline):
    from moviepy import AudioFileClip, CompositeAudioClip

    audio_clips = []
    for span in tl.spans:
        line = script.exchanges[span.index]
        if line.wav_path and Path(line.wav_path).exists():
            audio_clips.append(AudioFileClip(line.wav_path).with_start(span.start))
    if not audio_clips:
        return None
    return CompositeAudioClip(audio_clips)


# ---- エントリポイント -------------------------------------------------------


def render_script(script_path: Path, out: Path, preview: bool = False) -> RenderResult:
    """台本JSONファイルから動画を作る（CLI向けエントリポイント）。"""
    script = Script.model_validate_json(Path(script_path).read_text(encoding="utf-8"))
    return render_script_object(script, out, preview=preview)


def render_script_object(script: Script, out: Path, preview: bool = False) -> RenderResult:
    """メモリ上の Script（TTS/imagegen実行済み）から動画を作る（pipeline向け）。"""
    missing = [i for i, ln in enumerate(script.exchanges) if ln.duration_sec is None]
    if missing:
        raise ValueError(
            f"line {missing} に duration_sec がありません。先にTTS(studio pipeline)で実測尺を"
            "付与するか、sample.json のように事前に埋めてください。"
        )

    lines = [(ln.speaker, ln.emotion, float(ln.duration_sec)) for ln in script.exchanges]
    broll_starts_lines = [b.start_line for b in script.brolls]
    tl = build_timeline(lines, [0.0])  # broll開始は下で正確に算出するのでダミー
    # change_events を正確な broll 開始で組み直す
    broll_start_times = [tl.spans[i].start for i in broll_starts_lines]
    tl = build_timeline(lines, broll_start_times)

    layers: list[ImageClip] = []
    layers += _background_layers(script, tl)
    layers += _tempo_autozoom_layers(script, tl)
    layers += _character_layers(tl)
    layers += _subtitle_layers(script, tl)
    layers += _telop_layers(script, tl)
    layers += _top_layers(script, tl)
    layers += _accent_layers(script, tl)

    video = CompositeVideoClip(layers, size=layout.CANVAS).with_duration(tl.total)

    audio = _build_audio(script, tl)
    if audio is not None:
        video = video.with_audio(audio)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = 15 if preview else layout.FPS
    preset = "ultrafast" if preview else "medium"
    video.write_videofile(
        str(out),
        fps=fps,
        codec="libx264",
        audio_codec="aac" if audio is not None else None,
        audio=audio is not None,
        preset=preset,
        logger=None,
    )
    video.close()
    return RenderResult(path=out, duration_sec=tl.total)
